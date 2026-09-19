import re, json

# (여기에 실제로 GPT가 준 문자열을 넣으세요)
gpt_response = """```json
{
  "pages": [
    {"text": "작은 마을에 사는 용감한 소년, 민우가 있었습니다. 민우는 항상 새로운 모험을 꿈꾸며 숲속을 탐험하는 것을 좋아했습니다. 어느 날, 그는 숲속 깊은 곳에서 빛나는 보물 상자를 발견하게 되었고, 그 상자를 열어보기로 결심했습니다. 상자 안에는 신비로운 지도가 들어 있었고, 지도는 마법의 세계로 가는 길을 안내하고 있었습니다. 민우는 두근거리는 마음으로 지도를 따라 모험을 떠나기로 했습니다."},
    {"text": "민우는 지도를 따라 걸어가던 중, 두 갈래 길에 다다랐습니다. 왼쪽 길은 밝고 환한 꽃들이 만발한 길이었고, 오른쪽 길은 어두운 동굴로 이어지는 길이었습니다. 민우는 어떤 길을 선택할지 고민했습니다. 꽃으로 가득한 길로 가면 행복한 생명체들을 만날 수 있을 것 같았고, 동굴로 가면 신비로운 보물을 찾을 수 있을 것 같았습니다.", 
     "choices": [
       {"label":"A: 꽃이 만발한 길로 간다.","prompt":"민우는 환한 꽃길을 선택했습니다."},
       {"label":"B: 어두운 동굴로 간다.","prompt":"민우는 신비로운 동굴을 선택했습니다."}
     ]
    }
  ]
}
```
"""

# 1) JSON 블록만 뽑아내기
m = re.search(r"```json\s*([\s\S]*?)```", gpt_response)
raw = m.group(1).strip() if m else gpt_response

# 2) 파싱 및 구조 확인
data = json.loads(raw)
pages = data["pages"]
for i, page in enumerate(pages):
    print(f"Page {i+1}:", page.keys())
    print("  text =", page["text"][:30], "…")
    print("  has choices?", "choices" in page)