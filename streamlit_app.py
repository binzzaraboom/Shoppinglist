"""쇼핑 리스트 — Streamlit 버전 (PRD.md 기준)

실행: streamlit run streamlit_app.py
데이터는 같은 폴더의 shopping_list.json 에 저장된다 (웹 버전의 localStorage 대신).
"""

import html
import json
import os
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

# 저장 파일 경로
DATA_FILE = Path(__file__).with_name("shopping_list.json")

# 아이템 이름 최대 길이 (PRD 3.1)
MAX_NAME_LENGTH = 50


# ===== 데이터 =====

def normalize_name(value):
    """이름을 정리하고 유효하면 반환, 아니면 None (앞뒤 공백 제거, 1~50자)"""
    if not isinstance(value, str):
        return None
    name = value.strip()[:MAX_NAME_LENGTH]
    return name or None


def load_items():
    """저장 파일에서 아이템 목록을 불러온다 (손상된 데이터는 걸러낸다)"""
    try:
        parsed = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []

    seen_ids = set()
    items = []
    for raw in parsed:
        if not isinstance(raw, dict):
            continue
        item_id = raw.get("id")
        name = normalize_name(raw.get("name"))
        if not isinstance(item_id, str) or not item_id or item_id in seen_ids or not name:
            continue
        seen_ids.add(item_id)
        created_at = raw.get("createdAt")
        items.append({
            "id": item_id,
            "name": name,
            "checked": raw.get("checked") is True,
            "createdAt": created_at if isinstance(created_at, str) else now_iso(),
        })
    return items


def save_items(items):
    """아이템 목록을 저장 파일에 기록한다 (임시 파일에 쓴 뒤 교체해 파일 손상 방지)"""
    try:
        fd, tmp_path = tempfile.mkstemp(dir=DATA_FILE.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        # Windows에서는 다른 프로세스가 파일을 읽는 중이면 교체가 거부되므로 잠깐 기다렸다 다시 시도한다
        for attempt in range(5):
            try:
                os.replace(tmp_path, DATA_FILE)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05)
    except OSError as error:
        st.toast(f"쇼핑 리스트를 저장하지 못했어요: {error}", icon="⚠️")


@st.cache_resource
def get_data_lock():
    """모든 세션(탭·사용자)이 공유하는 저장 파일 잠금"""
    return threading.Lock()


def read_items():
    """잠금을 잡고 최신 아이템 목록을 읽는다"""
    with get_data_lock():
        return load_items()


@contextmanager
def update_items():
    """잠금을 잡은 채로 읽기 → 변경 → 저장한다 (동시에 저장해도 서로 덮어쓰지 않게)"""
    with get_data_lock():
        items = load_items()
        yield items
        save_items(items)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def find_item(items, item_id):
    return next((item for item in items if item["id"] == item_id), None)


# ===== 동작 (위젯 콜백) =====
# 매번 잠금을 잡고 파일에서 최신 목록을 읽은 뒤 변경해서 저장한다 (update_items).
# 그래서 여러 탭·사용자가 동시에 써도 서로의 변경을 덮어쓰지 않는다.

def add_item():
    """새 아이템을 리스트 맨 아래에 추가한다"""
    name = normalize_name(st.session_state.get("new_item", ""))
    if not name:
        return
    with update_items() as items:
        items.append({"id": str(uuid.uuid4()), "name": name, "checked": False, "createdAt": now_iso()})
    st.session_state.editing_id = None


def toggle_item(item_id, widget_key):
    """아이템의 구매 완료 상태를 체크박스 값으로 바꾼다"""
    with update_items() as items:
        item = find_item(items, item_id)
        if item:
            item["checked"] = bool(st.session_state[widget_key])
    st.session_state.editing_id = None


def start_edit(item_id):
    """아이템 편집 모드를 시작한다 (다른 아이템 편집 중이면 취소됨)"""
    st.session_state.editing_id = item_id


def save_edit(item_id):
    """편집 내용을 저장한다 (빈 값이면 원래 이름 유지)"""
    name = normalize_name(st.session_state.get(f"edit_{item_id}", ""))
    if name:
        with update_items() as items:
            item = find_item(items, item_id)
            if item:
                item["name"] = name
    st.session_state.editing_id = None


def cancel_edit():
    """편집을 취소하고 원래 이름으로 되돌린다"""
    st.session_state.editing_id = None


def delete_item(item_id):
    """아이템을 삭제한다"""
    with update_items() as items:
        items[:] = [item for item in items if item["id"] != item_id]
    if st.session_state.editing_id == item_id:
        st.session_state.editing_id = None


# ===== 화면 =====
# 사용자 입력(아이템 이름)은 마크다운 위젯에 넣지 않고 html.escape 후 st.html로 표시한다.
# 마크다운은 이스케이프해도 :material/아이콘: 같은 문법이 해석되기 때문이다.

@st.dialog("아이템 삭제")
def confirm_delete(item):
    st.html(f"<p>'{html.escape(item['name'])}'을(를) 삭제할까요?</p>")
    with st.container(horizontal=True, horizontal_alignment="right"):
        if st.button("취소", key="dialog_cancel"):
            st.rerun()
        if st.button("삭제", key="dialog_confirm", type="primary"):
            delete_item(item["id"])
            st.rerun()


def render_item_row(item):
    """일반 모드의 아이템 행"""
    item_id = item["id"]
    # 체크 상태가 key에 포함되어, 다른 탭에서 상태가 바뀌어도 위젯이 최신 값으로 다시 만들어진다
    checkbox_key = f"chk_{item_id}_{item['checked']}"
    # 이름은 마크다운이 아닌 이스케이프한 HTML로 표시한다 (서식·아이콘 문법이 해석되지 않게)
    name = html.escape(item["name"])
    if item["checked"]:
        name = f"<del>{name}</del>"

    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        # 체크박스 라벨은 화면에 숨기고 접근성 이름으로만 쓴다 (라벨이 그대로 aria-label이 됨)
        st.checkbox(
            f"{item['name']} 구매 완료 표시",
            value=item["checked"],
            key=checkbox_key,
            on_change=toggle_item,
            args=(item_id, checkbox_key),
            label_visibility="collapsed",
        )
        color = "color: #5b6760;" if item["checked"] else ""
        st.html(f'<span style="overflow-wrap: anywhere; {color}">{name}</span>')
        st.button("수정", key=f"edit_btn_{item_id}", type="tertiary",
                  help=f"{item['name']} 수정", on_click=start_edit, args=(item_id,))
        if st.button(":red[삭제]", key=f"del_btn_{item_id}", type="tertiary",
                     help=f"{item['name']} 삭제"):
            confirm_delete(item)


def render_edit_row(item):
    """편집 모드의 아이템 행 (Enter = 저장)"""
    item_id = item["id"]
    with st.form(f"edit_form_{item_id}", border=False):
        with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
            st.text_input(
                f"{item['name']} 이름 수정",
                value=item["name"],
                max_chars=MAX_NAME_LENGTH,
                key=f"edit_{item_id}",
                label_visibility="collapsed",
                width="stretch",
            )
            # Enter를 누르면 첫 번째 제출 버튼(저장)이 실행된다
            st.form_submit_button("저장", type="primary", on_click=save_edit, args=(item_id,))
            st.form_submit_button("취소", on_click=cancel_edit)


def main():
    st.set_page_config(page_title="쇼핑 리스트", page_icon="🛒", layout="centered")
    st.session_state.setdefault("editing_id", None)

    items = read_items()

    st.title("🛒 쇼핑 리스트")

    # 추가 폼 (Enter 또는 [추가] 버튼, 제출 후 입력창 비움)
    with st.form("add_form", clear_on_submit=True, border=False):
        with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
            st.text_input(
                "살 물건 이름",
                key="new_item",
                max_chars=MAX_NAME_LENGTH,
                placeholder="살 물건을 입력하세요...",
                label_visibility="collapsed",
                width="stretch",
            )
            st.form_submit_button("추가", type="primary", on_click=add_item)

    # 아이템 목록
    if not items:
        st.info("쇼핑 리스트가 비어 있어요. 살 물건을 추가해 보세요!")
    else:
        for item in items:
            if item["id"] == st.session_state.editing_id:
                render_edit_row(item)
            else:
                render_item_row(item)

    # 진행 상황
    st.divider()
    done_count = sum(item["checked"] for item in items)
    st.progress(
        done_count / len(items) if items else 0.0,
        text=f"{len(items)}개 중 {done_count}개 구매 완료",
    )


main()
