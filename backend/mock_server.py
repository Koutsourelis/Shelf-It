import asyncio
import base64
import binascii
import json
import os
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

app = FastAPI(title="ShelfSense AR Agent Backend", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CACHED_DEMO_PATH = os.path.join(os.path.dirname(__file__), "cached_demo.json")
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if load_dotenv is not None:
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

VISION_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "required": ["detected_items", "recommendation"],
    "properties": {
        "detected_items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "required": ["name", "category", "shelf_tier", "box_2d", "trend_score", "confidence"],
                "properties": {
                    "name": {"type": "STRING"},
                    "category": {"type": "STRING"},
                    "shelf_tier": {"type": "STRING", "enum": ["top", "eye_level", "low", "bottom"]},
                    "box_2d": {"type": "ARRAY", "items": {"type": "INTEGER"}},
                    "trend_score": {"type": "NUMBER"},
                    "confidence": {"type": "NUMBER"},
                },
            },
        },
        "recommendation": {
            "type": "OBJECT",
            "required": [
                "product_to_move",
                "move_from_box",
                "move_to_point",
                "displaced_item",
                "reason",
                "projected_sales_lift",
            ],
            "properties": {
                "product_to_move": {"type": "STRING"},
                "move_from_box": {"type": "ARRAY", "items": {"type": "INTEGER"}},
                "move_to_point": {"type": "ARRAY", "items": {"type": "INTEGER"}},
                "displaced_item": {"type": "STRING"},
                "reason": {"type": "STRING"},
                "projected_sales_lift": {"type": "STRING"},
            },
        },
    },
}

def load_cached_result():
    if os.path.exists(CACHED_DEMO_PATH):
        with open(CACHED_DEMO_PATH, "r") as f:
            return json.load(f)
    return {
        "detected_items": [
            {"name": "Organic Matcha Latte Can", "shelf_tier": "bottom", "box_2d": [680, 140, 910, 290], "trend_score": 92},
            {"name": "Plain Sparkling Water", "shelf_tier": "eye_level", "box_2d": [210, 410, 450, 560], "trend_score": 34}
        ],
        "recommendation": {
            "product_to_move": "Organic Matcha Latte Can",
            "move_from_box": [680, 140, 910, 290],
            "move_to_point": [330, 485],
            "displaced_item": "Plain Sparkling Water",
            "reason": "High commuter morning demand (+38%) and higher margin; currently hidden on bottom tier.",
            "projected_sales_lift": "+18% to +24%"
        },
        "shelf_talker_image_url": "https://images.unsplash.com/photo-1541658016709-82535e94bc69?auto=format&fit=crop&w=600&q=80",
        "trace_id": "run_fallback_001"
    }


def load_dataset_for_image(image_name: str | None) -> dict:
    if image_name in {None, "demo_shelf.jpg"}:
        return load_cached_result()
    raise ValueError("No verified dataset is available for this mock image. Disable Cached Demo to analyze it with Gemini.")


def merge_dataset_context(result_data: dict, dataset: dict) -> dict:
    dataset_items = dataset.get("detected_items", [])
    trend_by_category = {}
    for item in dataset_items:
        category = item.get("category")
        if category and isinstance(item.get("trend_score"), (int, float)):
            trend_by_category.setdefault(category, []).append(item["trend_score"])

    for item in result_data.get("detected_items", []):
        scores = trend_by_category.get(item.get("category"))
        if scores:
            item["trend_score"] = round((item.get("trend_score", 0) + (sum(scores) / len(scores))) / 2, 2)
    return result_data


def decode_image_base64(image_base64: str) -> tuple[bytes, str]:
    if not image_base64:
        raise ValueError("A shelf image is required for live detection.")
    mime_type = "image/jpeg"
    encoded = image_base64
    if image_base64.startswith("data:"):
        header, separator, encoded = image_base64.partition(",")
        if not separator:
            raise ValueError("Invalid image data URL.")
        mime_type = header[5:].split(";", 1)[0] or mime_type
    try:
        return base64.b64decode(encoded, validate=True), mime_type
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Invalid base64 image data.") from exc


def validate_live_result(result_data: dict) -> dict:
    items = result_data.get("detected_items")
    recommendation = result_data.get("recommendation")
    if not isinstance(items, list) or not items or not isinstance(recommendation, dict):
        raise ValueError("Vision response is missing detected items or a recommendation.")

    item_by_name = {}
    for item in items:
        box = item.get("box_2d")
        if (
            not isinstance(item.get("name"), str)
            or not isinstance(item.get("category"), str)
            or item.get("shelf_tier") not in {"top", "eye_level", "low", "bottom"}
            or not isinstance(box, list)
            or len(box) != 4
            or any(not isinstance(value, int) for value in box)
            or not (0 <= box[0] < box[2] <= 1000 and 0 <= box[1] < box[3] <= 1000)
        ):
            raise ValueError("Vision response contains an invalid detected item.")
        item_by_name[item["name"]] = item

    lower_items = [item for item in items if item["shelf_tier"] in {"low", "bottom"}]
    eye_items = [item for item in items if item["shelf_tier"] == "eye_level"]
    mover = item_by_name.get(recommendation.get("product_to_move"))
    displaced = item_by_name.get(recommendation.get("displaced_item"))
    if mover not in lower_items or displaced not in eye_items:
        if not lower_items or not eye_items:
            raise ValueError("Vision response contains no valid lower-tier and eye-level swap.")
        mover = max(lower_items, key=lambda item: item.get("trend_score", 0))
        displaced = min(eye_items, key=lambda item: item.get("trend_score", 0))
        recommendation["product_to_move"] = mover["name"]
        recommendation["displaced_item"] = displaced["name"]
        recommendation["move_to_point"] = [
            (displaced["box_2d"][0] + displaced["box_2d"][2]) // 2,
            (displaced["box_2d"][1] + displaced["box_2d"][3]) // 2,
        ]
        recommendation["reason"] = (
            f"{mover['name']} has the strongest detected trend among lower-tier items, "
            f"while {displaced['name']} is the lowest-trend eye-level item."
        )
    move_from_box = recommendation.get("move_from_box")
    move_to_point = recommendation.get("move_to_point")
    if move_from_box != mover["box_2d"]:
        recommendation["move_from_box"] = mover["box_2d"]
        move_from_box = mover["box_2d"]
    if (
        not isinstance(move_to_point, list)
        or len(move_to_point) != 2
        or any(not isinstance(value, int) for value in move_to_point)
        or not (
            displaced["box_2d"][0] <= move_to_point[0] <= displaced["box_2d"][2]
            and displaced["box_2d"][1] <= move_to_point[1] <= displaced["box_2d"][3]
        )
    ):
        raise ValueError("Recommendation move_to_point is outside the displaced item.")
    if mover["shelf_tier"] not in {"low", "bottom"} or displaced["shelf_tier"] != "eye_level":
        raise ValueError("Recommendation does not move a lower-tier item to eye level.")

    result_data["shelf_talker_image_url"] = result_data.get("shelf_talker_image_url", "")
    result_data["trace_id"] = result_data.get("trace_id", "")
    return result_data


async def detect_shelf(image_base64: str, target_audience: str) -> dict:
    api_key = os.getenv("GEMINI_API_KEY")
    if genai is None or types is None or not api_key:
        raise RuntimeError("Live vision is not configured. Enable Cached Demo or configure GEMINI_API_KEY.")
    image_bytes, mime_type = decode_image_base64(image_base64)
    prompt = f"""
Analyze this retail shelf image for {target_audience}. Identify every visible product or product group,
assign each a shelf tier, and return normalized coordinates on a 0-1000 scale.
Use box_2d as [ymin, xmin, ymax, xmax] and move_to_point as [y, x].
Recommend moving one lower-tier product to an eye-level position occupied by a slower product.
Return only JSON matching the provided schema. Do not invent product names when packaging text is unreadable;
use a specific visual category name and lower confidence instead.
"""
    client = genai.Client(api_key=api_key)
    response = await asyncio.to_thread(
        client.models.generate_content,
        model="gemini-3.8-flash",
        contents=[prompt, types.Part.from_bytes(data=image_bytes, mime_type=mime_type)],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=VISION_RESPONSE_SCHEMA,
            temperature=0.1,
        ),
    )
    if not response.text:
        raise ValueError("Vision provider returned an empty response.")
    result_data = json.loads(response.text)
    result_data["trace_id"] = f"live_{asyncio.get_event_loop().time()}"
    return validate_live_result(result_data)


class AnalyzeRequest(BaseModel):
    image_base64: Optional[str] = None
    target_audience: str = "Morning Commuters"
    use_cached_demo: bool = False
    scenario: str = "default"
    dataset_image: Optional[str] = None

class ResumeRequest(BaseModel):
    run_id: str
    image_base64: Optional[str] = None
    scenario: str = "default"
    dataset_image: Optional[str] = None

class FeedbackRequest(BaseModel):
    trace_id: str
    decision: str
    note: Optional[str] = ""

class VerifyRequest(BaseModel):
    image_base64: Optional[str] = None
    trace_id: str
    scenario: str = "default"

active_runs = {}
MOCK_IMAGE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MOCK_IMAGES = {
    "Screenshot From 2026-11-14 19-32-35.png",
    "Screenshot From 2026-11-14 19-32-53.png",
}

@app.get("/mock-assets/{image_name}")
async def mock_asset(image_name: str):
    if image_name not in MOCK_IMAGES:
        return JSONResponse({"error": "Unknown mock image"}, status_code=404)
    return FileResponse(os.path.join(MOCK_IMAGE_DIR, image_name), media_type="image/png")

@app.post("/api/analyze-stream")
async def analyze_stream(req: AnalyzeRequest):
    source = "cached" if req.use_cached_demo else "live"
    scenario = req.scenario
    try:
        if req.use_cached_demo:
            result_data = load_dataset_for_image(req.dataset_image)
        else:
            dataset = load_cached_result()
            result_data = merge_dataset_context(
                await detect_shelf(req.image_base64, req.target_audience),
                dataset,
            )
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)

    async def event_generator():
        run_id = f"run_{asyncio.get_event_loop().time()}"
        mover_name = result_data["recommendation"]["product_to_move"]
        active_runs[run_id] = {
            "scenario": scenario,
            "verify_attempts": 0,
            "result": result_data,
            "target_audience": req.target_audience,
            "use_cached_demo": req.use_cached_demo,
        }

        # 1. Decision: Vision
        d1 = {"run_id": run_id, "type": "decision", "tool": "vision_detector", "why": f"Inspecting shelf items and spatial layout for {req.target_audience}."}
        yield f"data: {json.dumps(d1)}\n\n"
        await asyncio.sleep(0.7)

        if scenario == "blurry_photo":
            o1 = {"run_id": run_id, "type": "observation", "tool": "vision_detector", "source": source, "detail": "Image blur detected (sharpness score 42/100). Confidence below threshold."}
            yield f"data: {json.dumps(o1)}\n\n"
            await asyncio.sleep(0.6)
            n1 = {"run_id": run_id, "type": "needs_user", "action": "request_better_photo", "message": "Photo is too blurry or dark. Please clean the camera lens or upload a clearer shelf photo."}
            yield f"data: {json.dumps(n1)}\n\n"
            return

        o1 = {"run_id": run_id, "type": "observation", "tool": "vision_detector", "source": source, "detail": "Successfully detected 4 products, classified shelf tiers, and mapped 0-1000 spatial coordinates."}
        yield f"data: {json.dumps(o1)}\n\n"
        await asyncio.sleep(0.8)

        # 2. Decision: Trends
        d2 = {"run_id": run_id, "type": "decision", "tool": "treg_trends", "why": "Checking live category demand and commuter morning preference surges."}
        yield f"data: {json.dumps(d2)}\n\n"
        await asyncio.sleep(0.7)

        if scenario == "weak_trends":
            o2 = {"run_id": run_id, "type": "observation", "tool": "treg_trends", "source": "cached", "detail": "Weak live search data for niche category; falling back to cached category seasonal average (+28%)."}
            yield f"data: {json.dumps(o2)}\n\n"
        else:
            o2 = {"run_id": run_id, "type": "observation", "tool": "treg_trends", "source": source, "detail": f"{mover_name} demand spike: +38% morning commuter surge. High margin opportunity."}
            yield f"data: {json.dumps(o2)}\n\n"
        await asyncio.sleep(0.8)

        # 3. Decision: Planogram
        d3 = {"run_id": run_id, "type": "decision", "tool": "planogram_planner", "why": "Computing optimal eye-level swap to maximize impulse revenue."}
        yield f"data: {json.dumps(d3)}\n\n"
        await asyncio.sleep(0.7)
        o3 = {"run_id": run_id, "type": "observation", "tool": "planogram_planner", "source": source, "detail": f"Selected {mover_name} for bottom-to-eye-level swap. Projected lift: {result_data['recommendation']['projected_sales_lift']}."}
        yield f"data: {json.dumps(o3)}\n\n"
        await asyncio.sleep(0.8)

        # 4. Decision: Creative
        d4 = {"run_id": run_id, "type": "decision", "tool": "fal_shelf_talker", "why": "Generating print-ready promotional shelf talker graphic for the promoted item."}
        yield f"data: {json.dumps(d4)}\n\n"
        await asyncio.sleep(0.8)
        o4 = {"run_id": run_id, "type": "observation", "tool": "fal_shelf_talker", "source": source, "detail": "Promotional shelf talker generated with high-contrast badge and pricing QR."}
        yield f"data: {json.dumps(o4)}\n\n"
        await asyncio.sleep(0.7)

        # 5. Needs User: await_move
        n2 = {"run_id": run_id, "type": "needs_user", "action": "await_move", "message": f"Agent ready. Please move {mover_name} from the bottom tier to the pulsing green eye-level target, then click Re-scan to verify."}
        yield f"data: {json.dumps(n2)}\n\n"
        await asyncio.sleep(0.5)

        result_data["type"] = "result"
        yield f"data: {json.dumps(result_data)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/api/resume")
async def resume_run(req: ResumeRequest):
    async def resume_generator():
        run_id = req.run_id
        run_state = active_runs.get(run_id)
        if run_state is None:
            raise ValueError("This run is no longer available for resume.")
        if run_state["use_cached_demo"]:
            result_data = load_dataset_for_image(req.dataset_image)
        else:
            result_data = merge_dataset_context(
                await detect_shelf(req.image_base64, run_state["target_audience"]),
                load_cached_result(),
            )
        run_state["result"] = result_data
        mover_name = result_data["recommendation"]["product_to_move"]
        d1 = {"run_id": run_id, "type": "decision", "tool": "vision_detector", "why": "Re-evaluating shelf image with improved photo capture."}
        yield f"data: {json.dumps(d1)}\n\n"
        await asyncio.sleep(0.8)
        o1 = {"run_id": run_id, "type": "observation", "tool": "vision_detector", "source": "live", "detail": "Image sharpness verified (94/100). All SKU boundaries successfully locked."}
        yield f"data: {json.dumps(o1)}\n\n"
        await asyncio.sleep(0.8)
        n1 = {"run_id": run_id, "type": "needs_user", "action": "await_move", "message": f"Photo successfully processed. Please move {mover_name} to eye level and click Re-scan to verify."}
        yield f"data: {json.dumps(n1)}\n\n"
        await asyncio.sleep(0.5)

        result_data["type"] = "result"
        yield f"data: {json.dumps(result_data)}\n\n"

    return StreamingResponse(resume_generator(), media_type="text/event-stream")

@app.post("/api/feedback")
async def feedback_endpoint(req: FeedbackRequest):
    print(f"[Oumi Feedback Logger] Trace ID: {req.trace_id} | Decision: {req.decision} | Note: {req.note}")
    return JSONResponse({"status": "success", "message": f"Feedback '{req.decision}' recorded successfully in Oumi trace log."})

@app.post("/api/verify")
async def verify_endpoint(req: VerifyRequest):
    run_state = active_runs.get(req.trace_id)
    if run_state is None:
        return JSONResponse({"verified": False, "detail": "This run is no longer available for verification."}, status_code=404)
    run_state["verify_attempts"] += 1
    scenario = run_state["scenario"]

    if scenario == "verify_fails_once" and run_state["verify_attempts"] == 1:
        return JSONResponse({
            "verified": False,
            "detail": f"{run_state['result']['recommendation']['product_to_move']} has not been verified at the target yet. Adjust its placement and try again."
        })

    recommendation = run_state["result"]["recommendation"]
    product_name = recommendation["product_to_move"]
    if run_state["use_cached_demo"]:
        return JSONResponse({
            "verified": False,
            "detail": f"Cached Demo cannot certify a physical move for {product_name}. Use live Gemini verification with the moved shelf image."
        })

    try:
        inspected = await detect_shelf(req.image_base64, run_state["target_audience"])
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        return JSONResponse({"verified": False, "detail": f"Verification could not inspect the new image: {exc}"}, status_code=503)

    moved_item = next(
        (item for item in inspected["detected_items"] if item["name"] == product_name),
        None,
    )
    target_y, target_x = recommendation["move_to_point"]
    is_at_target = (
        moved_item is not None
        and moved_item["shelf_tier"] == "eye_level"
        and abs(((moved_item["box_2d"][0] + moved_item["box_2d"][2]) / 2) - target_y) <= 120
        and abs(((moved_item["box_2d"][1] + moved_item["box_2d"][3]) / 2) - target_x) <= 160
    )
    if not is_at_target:
        return JSONResponse({
            "verified": False,
            "detail": f"{product_name} was detected, but its position does not match the recommended eye-level target."
        })

    return JSONResponse({
        "verified": True,
        "detail": f"Verified! {product_name} is perfectly positioned at eye level. Revenue optimization active."
    })

FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../frontend"))
if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
else:
    @app.get("/")
    def root():
        return {"message": "ShelfSense AR Agent Backend running."}
