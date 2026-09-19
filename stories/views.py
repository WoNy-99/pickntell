import os
from django.core.files.storage import FileSystemStorage
from django.shortcuts import render, render, HttpResponse, redirect
from django.http import JsonResponse
from django.conf import settings
from django.views.decorators.http import require_POST

import cv2
from PIL import Image

from pathlib import Path
from openai import OpenAI
import requests
from langdetect import detect, LangDetectException
import os, shutil

from elevenlabs import play
from elevenlabs.client import ElevenLabs
from elevenlabs import save
from elevenlabs.core.api_error import ApiError
import pprint
import random

import base64

import json
import re
import time
import uuid 

import logging
logger = logging.getLogger(__name__)


from dotenv import load_dotenv
load_dotenv('config.env')

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
STABLE_DIFFUSION_API_KEY = os.getenv('STABLE_DIFFUSION_API_KEY')
ELEVEN_LABS_API_KEY = os.getenv('ELEVEN_LABS_API_KEY')
MUBERT_API_KEY = os.getenv('MUBERT_API_KEY')

# Main page path (Typeing informations about fairy tale user want)
def home(request):
    return render(request, '1start.html')

# Second page path (Generate and Show the fairy tale)
@require_POST
def generate_story(request):
    age = request.POST.get('age')
    gender = request.POST.get('gender')
    genre = request.POST.get('genre')
    characters = request.POST.getlist('characters[]')
    details = request.POST.get('details', False)
    print(age, gender, genre, characters, details)
    
    base_seed = random.randint(0, 2**31 - 1)
    request.session['sd_base_seed'] = base_seed
    ### 1. Setting prompt ###
    system_input = (
        "너는 동화 작가야. 어린이 맞춤 모험 동화를 **2개의 연속된 단락**으로 만들어줘. "
        "아이의 나이에 맞게 길이를 조절해줘."
        "첫 번째 단락은 순수 텍스트로만, "
        "두 번째 단락 끝에 A/B 두 개의 선택지를 JSON 형식으로만 출력해줘. "
        "반환 형태는:\n```json\n"
        "{\n"
        "  \"pages\": [\n"
        "    {\"text\": \"첫 번째 문단 내용...\"},\n"
        "    {\"text\": \"두 번째 문단 내용...\", \n"
        "     \"choices\": [\n"
        "       {\"label\":\"A: …\",\"prompt\":\"…\"},\n"
        "       {\"label\":\"B: …\",\"prompt\":\"…\"}\n"
        "     ]\n"
        "    }\n"
        "  ]\n"
        "}\n```"
    )
    user_input = f"나이:{age}, 성별:{gender}, 장르:{genre}. "
    if characters:
        user_input += "등장인물:" + ",".join(characters) + ". "
    if details:
        user_input += "자세한 묘사 포함."
    ##########################
        
        
    ### 2. Generate a scenario ###
    gpt_resp = call_gpt(system_input, user_input)
    
    ### For debugging ###
    print(gpt_resp)
    # with open("./story.json", "r", encoding="utf-8") as file:
    #     story_json = json.load(file)
    #####################
        
    pages = parse_gpt_to_pages_with_choices(gpt_resp, request, scene_offset=0)
    # 1) 첫 장면 얼굴 추출
    first_img_url = pages[0]['image']
    # URL → 로컬 절대경로
    first_img_path = os.path.join(settings.MEDIA_ROOT, first_img_url.replace(settings.MEDIA_URL, ''))
    ref_face = extract_face(first_img_path)
    # 세션에 저장
    request.session['reference_face'] = ref_face
    
    pprint.pprint(pages)

    # 3) 세션에 저장
    request.session['pages']        = pages
    request.session['current_idx']  = 0
    request.session['branch_count'] = 0
    request.session['user_info']    = {
        'age': age,
        'gender': gender,
        'genre': genre,
        'characters': characters
    }
        # print(scenario)
    ##############################
    
    # 2) 줄거리 JSON 파일로 저장
    story_id = uuid.uuid4().hex
    story_dir = os.path.join(settings.MEDIA_ROOT, 'storylines')
    os.makedirs(story_dir, exist_ok=True)
    story_path = os.path.join(story_dir, f"{story_id}.json")
    # pages 리스트를 직렬화(텍스트·이미지·오디오·선택지 포함)
    with open(story_path, 'w', encoding='utf-8') as f:
        json.dump({'pages': pages}, f, ensure_ascii=False, indent=2)
    storyline_url = f"{settings.MEDIA_URL}storylines/{story_id}.json"

    return redirect('show_page', page_idx=0)

# ─────────── 7. 분기 처리 뷰 ───────────@
@require_POST
def branch_story(request):
    data         = json.loads(request.body)
    choice_idx   = data.get('choice_index')
    pages        = request.session.get('pages', [])
    current_idx  = request.session.get('current_idx', 0)
    branch_count = request.session.get('branch_count', 0)

    # 세션에서 꺼낸 유저 정보
    ui = request.session.get('user_info', {})
    age        = ui.get('age')
    gender     = ui.get('gender')
    genre      = ui.get('genre')
    characters = ui.get('characters', [])
    
    # 0) 최대 분기 수 체크 (여기선 2번까지만 허용)
    if branch_count >= 3:
        return JsonResponse({'new_pages': [], 'cards': []})

    # 1) 분기 카운트 **먼저** 올리기
    branch_count += 1
    request.session['branch_count'] = branch_count

    # 2) 기존 로직 그대로…
    page = pages[current_idx]
    if 'choices' not in page or choice_idx not in (0,1):
        return JsonResponse({'error':'잘못된 선택입니다.'}, status=400)
    choice = page['choices'][choice_idx]
    context_text = "\n".join(p['text'] for p in pages)

    

    # 4) GPT 프롬프트: 항상 2페이지, 두 번째에만 choices (마지막 분기 시엔 둘 다 텍스트)
    if branch_count == 1:
        system_input = (
            "너는 동화 작가야. 너는 이미 한 번 이야기를 만들었고, 앞선 이야기를 사용자의 선택에 따라 진행해야 해."
            "어린이 맞춤 모험 동화를 **2개의 연속된 단락**으로 만들어줘. "
            "아이의 나이에 맞게 길이를 조절해줘."
            "첫 번째 단락은 순수 텍스트로만, "
            "두 번째 단락 끝에 A/B 두 개의 선택지를 JSON 형식으로만 출력해줘. "
            "반환 형태는:\n```json\n"
            "{\n"
            "  \"pages\": [\n"
            "    {\"text\": \"첫 번째 문단 내용...\"},\n"
            "    {\"text\": \"두 번째 문단 내용...\", \n"
            "     \"choices\": [\n"
            "       {\"label\":\"A: …\",\"prompt\":\"…\"},\n"
            "       {\"label\":\"B: …\",\"prompt\":\"…\"}\n"
            "     ]\n"
            "    }\n"
            "  ]\n"
            "}\n```"
        )
    else:
        system_input = (
            "너는 동화 작가야. 너는 이미 두 번 이야기를 만들었고, 이제 마지막 이야기를 만들어야 해. 사용자의 선택에 따라 이야기를 마무리 해줘."
            "어린이 맞춤 모험 동화를 **2개의 연속된 단락**으로 만들어줘. "     
            "아이의 나이에 맞게 길이를 조절해줘."
            "반환 형태는:\n```json\n"
            "{\n"
            "  \"pages\": [\n"
            "    {\"text\": \"첫 번째 문단 내용...\"},\n"
            "    {\"text\": \"두 번째 문단 내용...\"}\n"
            "  ]\n"
            "}\n```"
        )
        
    user_input  = f"나이:{age}, 성별:{gender}, 장르:{genre}."
    
    if characters:
        user_input += " 등장인물:" + ",".join(characters) + "."
    # 지금까지 전개
    user_input += f"\n\n지금까지 이야기:\n{context_text}"
    # 다음 전개
    user_input += f"\n\n다음 전개: {choice['prompt']}"
        
    # GPT 호출 & 파싱
    resp = call_gpt(system_input, user_input)   
    current_pages = request.session.get('pages', [])
    new_pages = parse_gpt_to_pages_with_choices(resp, request, scene_offset=len(current_pages))

    # 세션 pages 업데이트
    pages.extend(new_pages)

    # 두 번째(마지막) 분기 종료 시점에만 GPT로 카드 생성 → 페이지에 붙이기
    response_pages = new_pages
    cards = []
    if branch_count == 2:
        # 지금까지의 텍스트를 모두 모아서 카드 생성
        full_text = "\n".join(p['text'] for p in pages)
        cards = generate_discussion_cards(full_text)
        card_page = {'cards': cards}
        pages.append(card_page)
        response_pages = new_pages + [card_page]
    # 세션에도 최종 pages 저장
    request.session['pages'] = pages

    # 새로 추가될 페이지 인덱스
    request.session['current_idx'] = len(pages) - len(response_pages)

    return JsonResponse({
        'new_pages': response_pages,
        'cards': cards
    })

def send_generation_request(
    host,
    params,
    files = None
):
    headers = {
        "Accept": "image/*",
        "Authorization": f"Bearer {STABLE_DIFFUSION_API_KEY}"
    }

    if files is None:
        files = {}

    # Encode parameters
    image = params.pop("image", None)
    mask = params.pop("mask", None)
    if image is not None and image != '':
        files["image"] = open(image, 'rb')
    if mask is not None and mask != '':
        files["mask"] = open(mask, 'rb')
    if len(files)==0:
        files["none"] = ''

    # Send request
    print(f"Sending REST request to {host}...")
    response = requests.post(
        host,
        headers=headers,
        files=files,
        data=params
    )
    if not response.ok:
        raise Exception(f"HTTP {response.status_code}: {response.text}")

    return response

def send_async_generation_request(
    host,
    params,
    files = None
):
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {STABLE_DIFFUSION_API_KEY}"
    }

    if files is None:
        files = {}

    # Encode parameters
    image = params.pop("image", None)
    mask = params.pop("mask", None)
    if image is not None and image != '':
        files["image"] = open(image, 'rb')
    if mask is not None and mask != '':
        files["mask"] = open(mask, 'rb')
    if len(files)==0:
        files["none"] = ''

    # Send request
    print(f"Sending REST request to {host}...")
    response = requests.post(
        host,
        headers=headers,
        files=files,
        data=params
    )
    if not response.ok:
        raise Exception(f"HTTP {response.status_code}: {response.text}")

    # Process async response
    response_dict = json.loads(response.text)
    generation_id = response_dict.get("id", None)
    assert generation_id is not None, "Expected id in response"

    # Loop until result or timeout
    timeout = int(os.getenv("WORKER_TIMEOUT", 500))
    start = time.time()
    status_code = 202
    while status_code == 202:
        print(f"Polling results at https://api.stability.ai/v2beta/results/{generation_id}")
        response = requests.get(
            f"https://api.stability.ai/v2beta/results/{generation_id}",
            headers={
                **headers,
                "Accept": "*/*"
            },
        )

        if not response.ok:
            raise Exception(f"HTTP {response.status_code}: {response.text}")
        status_code = response.status_code
        time.sleep(10)
        if time.time() - start > timeout:
            raise Exception(f"Timeout after {timeout} seconds")

    return response

# 1) SD API 호출 → 파일 시스템에 저장하고 절대경로 반환
def _sd_generate_image(prompt, negative_prompt="", aspect_ratio="16:9", seed=0, output_format="jpeg", files=None):

    host = "https://api.stability.ai/v2beta/stable-image/generate/core"
    params = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "aspect_ratio": aspect_ratio,
        "seed": seed,
        "output_format": output_format
    }

    try:
        response = send_generation_request(host, params, files)
        response.raise_for_status()
    except requests.HTTPError as e:
        # 500 에러라면 JSON 파싱 시도
        if e.response.status_code == 500:
            err = e.response.json()
            err_id   = err.get("id")
            err_name = err.get("name")
            messages = err.get("errors", [])
            logger.error(f"SD internal error {err_id} ({err_name}): {messages}")
            # 사용자에게 보여줄 친절한 메시지
            raise RuntimeError("이미지 생성 중 서버 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")
        raise

    # 응답 데이터 처리
    output_image = response.content
    finish_reason = response.headers.get("finish-reason")
    response_seed = response.headers.get("seed", str(uuid.uuid4()))  # 없으면 UUID 사용

    # NSFW 필터링 확인
    if finish_reason == "CONTENT_FILTERED":
        raise Warning("Generation failed due to NSFW content.")

    # 저장 디렉토리 설정
    images_dir = os.path.join(settings.MEDIA_ROOT, 'images')
    os.makedirs(images_dir, exist_ok=True)  # 디렉토리 생성 (존재하면 무시)

    # 파일 이름 및 경로 설정
    generated_filename = f"generated_{response_seed}.{output_format}"
    file_path = os.path.join(images_dir, generated_filename)

    # 파일 저장
    with open(file_path, "wb") as f:
        f.write(output_image)

    print(f"Image saved as: {file_path}")
    return file_path



# 2) 웹에 띄울 URL 반환용 래퍼
def generate_image_from_prompt(prompt: str, scene_number: int, request) -> str:
    """
    prompt → SD API 호출 → 파일 저장 → MEDIA_URL 기반 웹경로 반환
    """
    # 1) 번역
    en_prompt = translate_to_english(prompt)
    logger.info(f"Translated prompt for SD: {en_prompt}")

    # 2) 세션에 저장된 베이스 시드 불러오기
    base_seed = request.session.get('sd_base_seed', 0)
    # scene마다 다른 seed를 쓰되, 같은 base_seed를 공유
    use_seed = base_seed + scene_number
    
    # reference image 준비 (scene 2번부터)
    ref = request.session.get('reference_face')
    files = None
    if scene_number > 1 and ref:
        files = {"image": open(ref, 'rb')}   # ControlNet input

    # 3) 이미지 생성
    absolute_path = _sd_generate_image(
        en_prompt,
        seed=use_seed,
        files=files
    )
    relative_path = Path(absolute_path).relative_to(settings.MEDIA_ROOT)
    return f"{settings.MEDIA_URL}{relative_path}"


def generate_TTS(scene_number, story):
    client = ElevenLabs(
        api_key = ELEVEN_LABS_API_KEY
    )
    
    audio = client.generate(
            text=story,
            voice="ksaI0TCD9BstzEzlxj4q",
            model="eleven_multilingual_v2"
    )

        # 저장 디렉토리 설정
    audio_dir = os.path.join(settings.MEDIA_ROOT, 'audios')
    os.makedirs(audio_dir, exist_ok=True)  # 디렉토리 생성 (존재하면 무시)

        # 파일 이름 및 경로 설정
    random_uuid = uuid.uuid4()
    generated_filename = f"generated_{scene_number}_{random_uuid}.mp3"
    file_path = os.path.join(audio_dir, generated_filename)

    save(audio, file_path)
    

    
    print(f"Audio content written to file: {file_path}")

    return file_path


def generate_tts_from_text(scene_number: int, text: str) -> str:
    """
    ElevenLabs TTS API 호출 → 단일 음성 파일 생성 후
    MEDIA_ROOT/audios/ 에 저장하고 웹 접근 가능한 URL 반환
    """
    absolute_path = generate_TTS(scene_number, text)
    relative_path = Path(absolute_path).relative_to(settings.MEDIA_ROOT)
    return f"{settings.MEDIA_URL}{relative_path}"



# ──── 공통 헬퍼들 ─────────────────────────────────────────

def call_gpt(system: str, user: str) -> str:
    client = OpenAI()
    
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role":"system", "content": system},
            {"role":"user",   "content": user},
        ],
        temperature=0.7,
        max_tokens=800,
    )
    return resp.choices[0].message.content



def make_page(entry: dict, scene_number: int = 0, request=None) -> dict:
    """
    entry = { 'text': str, 'choices'?: [...] }
    scene_number는 TTS 파일명 구분용입니다.
    """
    text = entry["text"].strip()
    print(text)

    # 1) SD 이미지 한 장
    img_url = generate_image_from_prompt(text, scene_number, request)

    # 2) TTS 한 개
    audio_url = generate_tts_from_text(scene_number, text)

    page = { "text": text, "image": img_url, "audio": audio_url }
    if entry.get("choices"):
        page["choices"] = entry["choices"]
    return page

def extract_json(text: str) -> str:
    # 1) ```json … ``` 블록 안에 있는 배열/객체
    m = re.search(r"```json\s*([\s\S]*?)\s*```", text)
    if m:
        return m.group(1).strip()

    # 2) 배열(JSON Array) 먼저 찾기
    m = re.search(r"(\[\s*[\s\S]*?\s*\])", text)
    if m:
        return m.group(1)

    # 3) 객체(JSON Object) 찾기
    m = re.search(r"(\{\s*[\s\S]*?\s*\})", text)
    if m:
        return m.group(1)

    raise ValueError("GPT 응답에서 JSON(배열 또는 객체)을 찾을 수 없습니다.")

def parse_gpt_to_pages_with_choices(gpt_response: str, request, scene_offset: int = 0) -> list:
    raw_json = extract_json(gpt_response)
    logger.debug("=== GPT JSON BLOCK ===\n%s\n=== END BLOCK ===", raw_json)
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        logger.error("JSON 파싱 실패: %s\n원본 gpt_response:\n%s", e, gpt_response)
        raise ValueError("GPT 응답을 JSON 으로 변환하는데 실패했습니다.")
    
    # JSON 내 pages 배열 가져오기
    entries = data.get("pages")
    if not isinstance(entries, list):
        raise ValueError("`pages` 필드가 리스트가 아닙니다.")

    pages = []
    entries = data["pages"]  
    for idx, entry in enumerate(entries, start=1 + scene_offset):
        pages.append(make_page(entry, scene_number=idx, request=request))
    return pages

def translate_to_english(text: str) -> str:
    """
    한국어 텍스트를 이미지 생성용 영어로 번역해 줍니다.
    OpenAI GPT에 간단하게 번역을 요청합니다.
    """
    system = "You are a helpful translator. Translate the following Korean text into concise English suitable for an image generation prompt."
    # 낮은 토크 수로 간단히 번역
    resp = call_gpt(system, text)
    # GPT 응답에 ```json``` 등 태그가 붙을 수 있으므로 정제
    return resp.strip().strip('`"\'')

@require_POST
def set_current_index(request):
    data = json.loads(request.body)
    idx  = data.get('page_index')
    if idx is None or not isinstance(idx, int):
        return JsonResponse({'error':'Invalid page index'}, status=400)
    request.session['current_idx'] = idx
    return JsonResponse({'ok': True})

def show_page(request, page_idx):
    pages = request.session.get('pages')
    user_info = request.session.get('user_info', {})

    if not pages:
        return redirect('home')

    if page_idx < 0 or page_idx >= len(pages):
        return HttpResponse('잘못된 페이지입니다.', status=404)

    request.session['current_idx'] = page_idx
    return render(request, '2story.html', {
        'pages': pages,
        'current_page': page_idx,
        'user_info': user_info
    })
    
def generate_bgm(genre: str) -> str:
    """
    Mubert API 를 호출해 BGM 스트림을 생성 → 다운로드 → MEDIA_ROOT/bgm/ 에 저장 → URL 반환
    """
    # 1) Mubert 에 채널(장르) 요청
    url = "https://api.mubert.com/v2/stream"
    params = {"apikey": MUBERT_API_KEY, "format": "mp3", "duration": 120, "genre": genre}
    resp = requests.get(url, params=params, stream=True)
    resp.raise_for_status()

    # 2) 파일로 저장
    bgm_dir = os.path.join(settings.MEDIA_ROOT, 'bgm')
    os.makedirs(bgm_dir, exist_ok=True)
    filename = f"bgm_{genre}_{uuid.uuid4().hex}.mp3"
    path = os.path.join(bgm_dir, filename)
    with open(path, 'wb') as f:
        for chunk in resp.iter_content(1024*10):
            f.write(chunk)

    return settings.MEDIA_URL + f"bgm/{filename}"

def generate_discussion_cards(context_text: str) -> list:
    system = (
        "너는 동화 작가이자 부모-자녀 대화 코치야. 아래 이야기를 바탕으로, "
        "부모와 아이가 함께 나눌 수 있는 5개의 질문을 JSON 배열 형식으로 만들어줘. "
        "출력 예시:\n```json\n"
        "[ {\"q\":\"질문1\"}, {\"q\":\"질문2\"}, … ]\n```"
    )
    user   = f"지금까지 이야기:\n{context_text}"
    resp   = call_gpt(system, user)

    raw_json = extract_json(resp)
    try:
        cards = json.loads(raw_json)
    except json.JSONDecodeError as e:
        logger.error("토론 카드 JSON 파싱 실패: %s\n원본:\n%s", e, raw_json)
        raise

    return cards  # [{'q': '…'}, …]


def extract_face(image_path):
    # OpenCV로 얼굴 검출
    img = cv2.imread(image_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    faces = cascade.detectMultiScale(gray, 1.1, 4)
    if len(faces) == 0:
        return None

    x, y, w, h = faces[0]
    # 잘라내기 & Pillow 로 저장
    pil = Image.open(image_path)
    face = pil.crop((x, y, x + w, y + h))

    ref_dir = os.path.join(settings.MEDIA_ROOT, 'reference')
    os.makedirs(ref_dir, exist_ok=True)
    face_path = os.path.join(ref_dir, 'character_face.png')
    face.save(face_path)
    return face_path
