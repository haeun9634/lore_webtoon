"""랜딩페이지 서버. 표준 라이브러리만 쓴다 (설치할 것 없음).

    python serve.py            # http://127.0.0.1:8800
    python serve.py --port 9000 --open

브라우저는 상태를 **폴링**한다. SSE 나 웹소켓이 아니라 0.8초마다 상태 JSON 을
받아 간다. 한 편 뽑는 데 10분이 걸리는 일이라 0.8초 지연은 보이지 않고,
연결이 끊겨도(노트북을 덮었다 열어도) 다음 폴링에서 그대로 이어진다 —
스트리밍이었다면 끊긴 자리를 복구해야 한다.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import mimetypes
import os
import re
import sys
import threading
import webbrowser
from html import escape as html_escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, quote

import accounts
import ownership
import visibility
import credits
import overlay
import pipeline
import newharness_pipeline as nh
import watermark

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"
# 화면 구경용으로 만들어 두는 것들. jobs/ 는 gitignore 라 저장소가 안 더러워진다.
DEMO_DIR = HERE / "jobs" / "_demo"
MAX_PHOTO_BYTES = 6 * 1024 * 1024

runner = pipeline.Runner()
nh_runner = nh.NHRunner()
_thumb_lock = threading.Lock()
_warned_no_pillow = False


# --------------------------------------------------------------------------- #
# 공유 링크의 미리보기 (Open Graph)
# --------------------------------------------------------------------------- #
#
# 카톡·트위터·디스코드에 링크를 붙이면 그쪽 크롤러가 주소를 한 번 받아 가서
# 미리보기 카드를 만든다. **크롤러는 자바스크립트를 안 돌린다** — app.js 가
# 화면에 그리는 제목·그림은 크롤러에게 안 보이고, 정적 index.html 의 기본
# <title> 만 읽어서 어느 작품이든 "LORE" 라고만 뜬다.
#
# 그래서 ?run= 이 붙은 주소일 때만 서버가 <head> 에 태그를 박아서 내보낸다.
# 파일을 고치는 것이 아니라 내보낼 때 문자열 하나를 끼우는 것이라, 화면 쪽
# 코드는 이것을 몰라도 된다.

OG_MARK = "</head>"


def og_tags(meta: dict, base: str) -> str:
    """공유 미리보기 태그. meta 는 pipeline.share_meta() 가 준 것."""
    ep, rid = meta["episode"], meta["run_id"]
    who = meta.get("character") or ""
    title = meta.get("title") or f"{ep}화"
    # "모모 · 약속의 무게, 장난의 시작" — 누구 이야기인지가 제목 앞에 와야
    # 카드만 보고도 자기 작품인지 안다.
    head = f"{who} · {title}" if who else title
    full = f"{head} — LORE"
    desc = (meta.get("logline") or "").strip()
    if not desc:
        # 로그라인이 없는 옛 run 도 있다. 빈 설명보다는 장르라도 말한다.
        genre = (meta.get("genre") or "").strip()
        desc = f"{genre} 웹툰" if genre else "캐릭터 한 명으로 만든 웹툰 한 화."
    img = (f"{base}/api/runs/{quote(rid, safe='')}/page/{meta['cover_page']}"
           f"?w=1080&ep={ep}")
    url = f"{base}/works?run={quote(rid, safe='')}&ep={ep}"
    e = html_escape
    return (
        f'<meta property="og:type" content="article">\n'
        f'<meta property="og:site_name" content="LORE">\n'
        f'<meta property="og:title" content="{e(full, quote=True)}">\n'
        f'<meta property="og:description" content="{e(desc, quote=True)}">\n'
        f'<meta property="og:image" content="{e(img, quote=True)}">\n'
        f'<meta property="og:url" content="{e(url, quote=True)}">\n'
        # 웹툰 한 장은 세로로 아주 길다. summary_large_image 로 주면 트위터가
        # 가로로 넓게 잘라서 첫 컷만 보이는데, 그게 세로 전체를 우겨넣어
        # 알아볼 수 없게 줄이는 것보다 낫다.
        f'<meta name="twitter:card" content="summary_large_image">\n'
        f'<meta name="twitter:title" content="{e(full, quote=True)}">\n'
        f'<meta name="twitter:description" content="{e(desc, quote=True)}">\n'
        f'<meta name="twitter:image" content="{e(img, quote=True)}">\n'
        f"<title>{e(full)}</title>\n"
    )


def warn_no_pillow() -> None:
    """Pillow 가 없다는 것을 콘솔에 **한 번만** 알린다.

    이 자리(줄이기)는 없어도 화면이 뜨기는 한다 — 부르는 쪽이 원본을 그대로
    내려보낸다. 그래서 조용히 넘어가면 아무도 모르는 채로 컷 한 장에 수 MB 씩
    나가고 결과 화면이 한참 안 열린다. 매 요청마다 찍으면 폴링 때문에 콘솔이
    못 쓰게 되므로 한 번만 찍는다.
    """
    global _warned_no_pillow
    if not _warned_no_pillow:
        _warned_no_pillow = True
        print("[경고] Pillow 가 없어 그림을 줄이지 못합니다 — 원본을 그대로 "
              "내려보냅니다(느립니다). 사진 업로드도 안 됩니다.\n"
              "        pip install Pillow")


def thumbnail(src: Path, dest: Path, width: int) -> Path:
    """웹으로 내려보낼 크기로 줄여 둔다.

    원본 컷은 2752x1536 짜리 PNG 다. 12장이면 30MB 가 넘어서 그대로 내려보내면
    결과 화면이 열리는 데만 한참 걸린다. 줄인 것은 job 폴더에 캐시한다.
    """
    if dest.exists() and dest.stat().st_mtime >= src.stat().st_mtime:
        return dest
    with _thumb_lock:
        try:
            from PIL import Image
        except ImportError:
            warn_no_pillow()
            raise
        im = Image.open(src)
        im.load()
        if im.width > width:
            h = round(im.height * width / im.width)
            im = im.resize((width, h), Image.LANCZOS)
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.convert("RGB").save(dest, "JPEG", quality=88, optimize=True)
    return dest


class Handler(BaseHTTPRequestHandler):
    server_version = "lore-landing"

    # 요청 한 줄씩 찍히면 폴링 때문에 콘솔이 못 쓰게 된다.
    def log_message(self, fmt, *args):  # noqa: A003
        pass

    # ---- 보내기 ------------------------------------------------------------ #

    def _send(self, code: int, body: bytes, ctype: str,
              headers: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _json(self, obj, code: int = 200, headers: dict[str, str] | None = None) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", headers)

    def _error(self, code: int, message: str, **extra) -> None:
        self._json({"error": message, **extra}, code)

    def _base_url(self) -> str:
        """이 요청이 온 주소의 뿌리. og:image·og:url 은 절대 주소여야 한다.

        프록시 뒤에 서면 브라우저가 본 주소와 서버가 들은 주소가 다르다 —
        앞에서 넘겨주는 값이 있으면 그쪽을 믿는다.
        """
        # 공개 주소를 못박아 둔 곳이 있으면 그것이 이긴다. 공유가 실제로
        # 되려면 남이 열 수 있는 주소여야 하는데, 여기서 들리는 것은 개발 중에
        # 127.0.0.1 이고 사설망에서는 192.168.x 다 — 그 주소를 카톡에 보내면
        # 받은 사람은 아무것도 못 연다. 배포하면 LORE_PUBLIC_URL 에 도메인을
        # 넣는다(#96).
        fixed = os.environ.get("LORE_PUBLIC_URL", "").strip().rstrip("/")
        if fixed:
            return fixed
        host = (self.headers.get("X-Forwarded-Host")
                or self.headers.get("Host") or "127.0.0.1")
        scheme = self.headers.get("X-Forwarded-Proto") or "http"
        return f"{scheme}://{host.split(',')[0].strip()}"

    def _page(self, path: Path, run_id: str = "", episode: int = 1) -> None:
        """index.html 을 내보낸다. ?run= 이 있으면 공유 미리보기 태그를 끼워서.

        태그는 파일에 안 남기고 내보낼 때만 끼운다 — 주소마다 값이 다르므로
        파일 하나에 박을 수가 없다.
        """
        meta = pipeline.share_meta(run_id, episode) if run_id else None
        if not meta:
            return self._file(path)        # 없는 작품이면 평소 화면 그대로
        try:
            html = path.read_text(encoding="utf-8")
        except OSError:
            return self._file(path)
        # 원래 <title> 은 지운다 — 안 지우면 둘이 남고 브라우저는 앞엣것을 쓴다.
        html = re.sub(r"<title>.*?</title>\s*", "", html, count=1, flags=re.S)
        block = og_tags(meta, self._base_url())
        html = html.replace(OG_MARK, block + OG_MARK, 1)
        self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

    # ---- 계정 세션(쿠키) ---------------------------------------------------- #
    #
    # 로그인 안 해도 웹툰은 그대로 만든다 — 계정은 "이 작품 나중에도 찾기"
    # 용 선택 기능이라, 세션 쿠키가 없어도 대부분의 자리는 그냥 게스트로 본다.

    def _session_cookie(self) -> str | None:
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == accounts.SESSION_COOKIE:
                return v
        return None

    def _account_key(self) -> str | None:
        return accounts.session_nickname_key(self._session_cookie())

    def _set_session_header(self, token: str) -> dict[str, str]:
        return {"Set-Cookie": f"{accounts.SESSION_COOKIE}={token}; Path=/; "
                              f"Max-Age={accounts.SESSION_MAX_AGE}; SameSite=Lax; HttpOnly"}

    def _clear_session_header(self) -> dict[str, str]:
        return {"Set-Cookie": f"{accounts.SESSION_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax; HttpOnly"}

    def _file(self, path: Path, download: str = "") -> None:
        if not path.exists() or not path.is_file():
            return self._error(404, "없습니다")
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        headers = {}
        if download:
            # HTTP 헤더는 latin-1 만 담을 수 있어서 파일 이름에 한글이 들어가면
            # send_header 가 터진다. 옛 브라우저용 ASCII 이름과 RFC 5987 의
            # filename* 을 같이 보낸다 — 요즘 브라우저는 뒤엣것을 쓴다.
            plain = re.sub(r"[^A-Za-z0-9._-]+", "_", download).strip("_") or "episode.png"
            headers["Content-Disposition"] = (
                f'attachment; filename="{plain}"; '
                f"filename*=UTF-8''{quote(download, safe='')}")
        self._send(200, path.read_bytes(), ctype, headers)

    def _demo_episode(self) -> None:
        """샘플 장 -> 한 편 -> 워터마크. 결과 화면 목업의 내려받기가 쓴다."""
        scenes = sorted((WEB / "samples" / "mock").glob("scene*.jpg"),
                        key=lambda p: int(re.sub(r"\D", "", p.stem) or 0))
        if not scenes:
            return self._error(404, "샘플이 없습니다")
        DEMO_DIR.mkdir(parents=True, exist_ok=True)
        out = DEMO_DIR / "episode.png"
        newest = max(p.stat().st_mtime for p in scenes)
        if not out.exists() or out.stat().st_mtime < newest:
            try:
                overlay._episode.stitch(scenes, out)
            except Exception as exc:                      # noqa: BLE001
                return self._error(500, f"샘플을 잇지 못했습니다: {exc}")
        src = watermark.for_download(out, DEMO_DIR, "모모 · 1화")
        return self._file(src, download="약속의_무게_1화.png")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _record_feedback(self, job, stage: str, decision: str, body: dict) -> str:
        """승인 화면에서 온 항목·자유 입력을 run 폴더에 남기고, 프롬프트에 실을
        글로 돌려준다.

        approve 에도 남긴다 — "이대로 진행"을 누르면서 불만을 적는 사람이 있고,
        그건 다음 판을 고칠 근거로는 오히려 더 정확하다. 다만 approve 는 다시
        만들지 않으므로 돌려주는 글은 쓰이지 않는다.
        """
        tags = pipeline.clean_tags(stage, body.get("tags"))
        text = str(body.get("feedback") or "").strip()[:pipeline.FEEDBACK_TEXT_MAX]
        if job.run_id:
            pipeline.append_feedback(job.run_id, stage, tags, text, decision=decision)
        return pipeline.author_note(stage, tags, text)

    # ---- 라우팅 ------------------------------------------------------------ #

    # 요청 하나가 터져도 서버는 계속 돌아야 한다. 브라우저는 0.8초마다
    # 물어보므로, 조용히 끊기면 화면이 멈춘 것처럼 보인다.
    def handle_one_request(self) -> None:
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True
        except Exception as exc:                                # noqa: BLE001
            print(f"[요청 오류] {self.path} — {type(exc).__name__}: {exc}")
            try:
                self._error(500, f"{type(exc).__name__}: {exc}")
            except Exception:                                   # noqa: BLE001
                pass
            self.close_connection = True

    @staticmethod
    def _ep(query: dict) -> int:
        """?ep=N — 몇 화를 볼 것인가. 없으면 1화다.

        주소에 회차를 **선택 항목**으로 둔 이유: 1화만 있던 시절의 주소가 그대로
        살아 있어야 한다. 편집기·결과 화면이 옛 주소로 저장해 둔 링크가 많다.
        """
        try:
            n = int((query.get("ep") or ["1"])[0])
        except (TypeError, ValueError):
            return 1
        return n if 1 <= n <= 999 else 1

    def do_GET(self) -> None:                                   # noqa: N802
        url = urlparse(self.path)
        path, query = url.path, parse_qs(url.query)

        if path in ("/", "/index.html"):
            return self._file(WEB / "index.html")
        # 편집실 — **목업**. 서버 상태가 필요 없고 web/samples/mock.json 만 읽는다.
        # 한 번도 안 돌려 본 사람도 결과물 화면을 그대로 볼 수 있어야 한다.
        if path in ("/editor", "/editor/", "/editor.html"):
            return self._file(WEB / "editor.html")
        # 화면 구경 — **목업**. 기다리는 화면(루·진행 바·딴짓·만지기)을 실제
        # 생성 없이 가짜 진행으로 돌려 본다. 과금 없음.
        if path in ("/demo", "/demo/", "/demo.html"):
            return self._file(WEB / "demo.html")
        # new_harness 연결 실험 화면. index.html/app.js 와 완전히 별개다 —
        # 제품 화면(index.html)은 아직 story-harness/webtoon-harness 를 쓰고,
        # 여기서만 new_harness 로 만든다 (newharness_pipeline.py 참고).
        if path in ("/nh", "/nh/", "/newharness", "/newharness.html"):
            return self._file(WEB / "newharness.html")
        # 결과 화면 **목업**. 실제 생성 없이 완성본 화면을 그대로 본다 — 같은
        # index.html·app.js 를 쓰고, 데이터만 web/samples/mock.json 에서 온다.
        if path in ("/demo/result", "/demo/result/"):
            return self._file(WEB / "index.html")
        # 마이페이지 — 로그인한 사람이 저장해 둔 작품. 목업도 같은 파일이다.
        if path in ("/mypage", "/mypage/", "/demo/mypage", "/demo/mypage/"):
            return self._file(WEB / "index.html")
        # 목업의 "내려받기". 샘플 장을 한 편으로 이어 붙인 뒤 **실제 내려받기와
        # 똑같은 길**로 내보낸다 — 그래야 워터마크가 붙은 모습이 그대로 보인다.
        if path == "/api/demo/episode.png":
            return self._demo_episode()
        # 이미 만들어 둔 결과물을 바로 여는 자리. 같은 index.html 인데,
        # app.js 가 주소를 보고 폼 대신 결과 화면부터 띄운다.
        if path in ("/result", "/result/"):
            return self._file(WEB / "index.html")
        # 내가 만든 웹툰 전부 — 완성본을 훑어보는 목록. job 을 거치지 않는다
        # (하네스를 직접 돌렸거나 이어 만든 회차도 여기 나와야 한다).
        #
        # **공유 링크가 닿는 자리이기도 하다.** ?run= 이 붙어 있으면 남이 보낸
        # 링크를 열었다는 뜻이라, 크롤러가 미리보기를 만들 수 있게 태그를 실어
        # 보낸다(_page). 사람이 열면 app.js 가 그 작품 완성본을 바로 띄운다.
        if path in ("/works", "/works/"):
            return self._page(WEB / "index.html",
                              (query.get("run") or [""])[0], self._ep(query))
        if path.startswith("/static/"):
            rel = path[len("/static/"):]
            target = (WEB / rel).resolve()
            if WEB.resolve() not in target.parents:
                return self._error(403, "밖입니다")
            return self._file(target)
        if path == "/api/config":
            return self._json({
                "styles": [{"key": k, "label": v} for k, v in pipeline.STYLES.items()],
                "fields": list(pipeline.FIELD_KEYS),
                "condition": pipeline.CONDITION,
                "cuts_per_sheet": pipeline.CUTS_PER_SHEET,
                "worlds": pipeline.world_presets(),
                # 단계별로 고를 수 있는 불만 항목. 화면이 목록을 들고 있지 않게
                # 해서, 항목을 늘릴 때 파이썬 한 군데만 고치면 되게 한다.
                "feedback_tags": pipeline.FEEDBACK_TAGS,
                "feedback_text_max": pipeline.FEEDBACK_TEXT_MAX,
                # 작가 규칙 글자수 상한 — 화면이 남은 글자수를 보여줄 근거
                "memory_always_max": pipeline.MEMORY_ALWAYS_MAX,
                "memory_keyword_max": pipeline.MEMORY_KEYWORD_MAX,
                # 카카오톡 공유는 카카오 SDK 를 써야 하고, developers.kakao.com
                # 에서 받은 JavaScript 키 + **등록된 도메인**이 있어야 한다.
                # 키가 없으면 화면이 그 단추를 아예 안 그린다 — 눌러도 안 되는
                # 단추를 두면 고장으로 읽힌다.
                "kakao_js_key": os.environ.get("KAKAO_JS_KEY", "").strip(),
                # 공유 링크에 쓸 공개 주소. 비어 있으면 화면이 지금 보고 있는
                # 주소를 쓴다(개발 중에는 그것이 localhost 다).
                "public_url": os.environ.get("LORE_PUBLIC_URL", "").strip().rstrip("/"),
                # 일반/전문 모드. 어느 단계에서 사람을 세우는지를 화면이 베껴
                # 두지 않게 서버가 준다 — 온보딩의 "무엇이 다른가" 설명과 실제
                # 동작이 갈라지면, 고른 사람이 속은 것이 된다.
                "modes": {
                    "simple": pipeline.checkpoints({}),
                    "expert": pipeline.checkpoints({"expert": True}),
                },
                "art_qa_regen_default": pipeline.ART_QA_REGEN_DEFAULT,
                "art_qa_regen_max": pipeline.ART_QA_REGEN_MAX,
                # 카카오톡 공유는 카카오 SDK 를 써야 하고, 그러려면
                # developers.kakao.com 에서 받은 JavaScript 키와 **등록된
                # 도메인**이 있어야 한다. 키가 없으면 화면이 그 단추를 아예 안
                # 그린다 — 눌러도 안 되는 단추를 두면 고장으로 읽힌다.
                # 키가 생기면 KAKAO_JS_KEY 를 넣고 서버를 다시 켜면 된다.
                "kakao_js_key": os.environ.get("KAKAO_JS_KEY", "").strip(),
                "title_max": pipeline.TITLE_MAX,
                # 크레딧 — 값 자체는 credits.py 가 유일한 출처. 화면의 비용
                # 표시(−N 크레딧)가 실제로 빠지는 값과 어긋나지 않게 여기서 받는다.
                "credit_cost": {
                    "full": credits.CREDIT_FULL,
                    # 만들 때 나가는 값 — 전액 선결제라 full 과 같다.
                    "preview": credits.CREDIT_FULL,
                    "webtoon_mult": credits.CREDIT_WEBTOON_MULT,
                },
                "credit_packages": credits.PACKAGES,
                "daily_free_credits": credits.DAILY_FREE_CREDITS,
                "account_photo_presets": accounts.PRESET_PHOTOS,
            })

        # 잔액 — uid 는 브라우저(localStorage)가 만들어 붙인다(계정이 없어서).
        if path == "/api/credits":
            uid = (query.get("uid") or [""])[0]
            if not credits.valid_uid(uid):
                return self._error(400, "uid 가 없습니다")
            return self._json({"balance": credits.balance(uid)})

        # 하루 1회 무료 크레딧 — 오늘 이미 받았는지만 본다(지급은 POST).
        # 충전 모달을 열 때마다 물어서 단추를 "오늘 받기/내일 다시" 로 바꾼다.
        if path == "/api/credits/daily":
            uid = (query.get("uid") or [""])[0]
            if not credits.valid_uid(uid):
                return self._error(400, "uid 가 없습니다")
            return self._json(credits.daily_claim_state(uid))

        # ---- 계정(선택 기능) ------------------------------------------------ #
        #
        # 로그인 안 해도(게스트) 웹툰은 그대로 만들 수 있다 — 여기 자리들은
        # "이 작품 나중에도 찾기" 를 원하는 사람만 쓴다.
        if path == "/api/account/me":
            key = self._account_key()
            if not key:
                return self._json({"logged_in": False})
            account = accounts.get_account(key)
            if not account:
                return self._json({"logged_in": False})
            return self._json({"logged_in": True, **accounts.public_info(key, account)})

        m = re.fullmatch(r"/api/account/avatar/([\w-]+)", path)
        if m:
            src = accounts.AVATARS_DIR / f"{m.group(1)}.jpg"
            if not src.exists():
                return self._error(404, "사진이 없습니다")
            return self._file(src)

        # 계정에 담아둔 작품 — list_runs() 를 재사용해서 claimed_runs 로 거른다.
        # run 자체에 소유자 개념을 새로 넣지 않는다(기존 목록·편집기가
        # run_id 만으로 도는 구조를 그대로 두고, "누구 것" 만 계정 쪽에 얹는다).
        if path == "/api/account/works":
            key = self._account_key()
            if not key:
                return self._error(401, "로그인이 필요합니다")
            account = accounts.get_account(key)
            claimed = set((account or {}).get("claimed_runs", []))
            runs = [r for r in pipeline.list_runs(limit=200) if r["run_id"] in claimed]
            # 내 것에는 숨긴 것도 그대로 나온다 — 대신 지금 공개 상태를 붙여서
            # 마이페이지가 껐다 켰다 할 수 있게 한다.
            return self._json({"runs": visibility.mark(runs)})

        # 편집기가 아무 run 이나 열 수 있게 하는 두 자리.
        # 작업(Job)을 거치지 않는다 — 하네스를 직접 돌린 run 도 똑같이 열린다.
        if path == "/api/runs":
            # 둘러보기에 걸리는 목록이다 — 숨긴 작품은 빼고 준다. new_harness
            # run 도 같은 모양으로 섞어 준다(nh.list_runs 가 classic 과 같은
            # 필드를 돌려준다) — 화면(app.js)은 어느 쪽에서 왔는지 몰라도 된다.
            runs = pipeline.list_runs() + nh.list_runs()
            return self._json({"runs": visibility.filter_public(runs)})

        m = re.fullmatch(r"/api/runs/([\w.-]+)/episode", path)
        if m:
            run_id = m.group(1)
            # story-harness 에 없고 new_harness 에 있으면 그쪽을 연다 — 위
            # /result·/page 와 같은 규칙이다. 이 자리에만 그 분기가 없어서
            # new_harness 로 만든 작품은 편집실이 안 열렸다.
            if not pipeline.episode_dir(run_id, 1).exists() and nh.is_run(run_id):
                data = nh.editor_data(run_id)
            else:
                data = pipeline.editor_data(run_id, self._ep(query))
            if not data:
                return self._error(404, "그 run 의 1화 컷을 찾지 못했습니다")
            return self._json(data)

        # "내 웹툰" 목록에서 바로 여는 완성본 — job 없이 run_id 로만 연다.
        # 하네스를 직접 돌렸거나 편집기의 "다음 화 이어서 만들기" 로 나온
        # 회차는 landing/jobs/ 에 기록이 없어서, job 기반 결과 화면(/api/jobs/…)
        # 으로는 못 열었다 (초롱 2화가 그랬다).
        m = re.fullmatch(r"/api/runs/([\w.-]+)/result", path)
        if m:
            run_id = m.group(1)
            # story-harness 에 없고 new_harness 에 있으면 그쪽 결과를 준다.
            if not pipeline.episode_dir(run_id, 1).exists() and nh.is_run(run_id):
                out = nh.result_by_run(run_id)
            else:
                out = pipeline.result_by_run(run_id, self._ep(query))
            if not out:
                return self._error(404, "그 회차의 결과물을 찾지 못했습니다")
            return self._json(out)

        m = re.fullmatch(r"/api/runs/([\w.-]+)/episode\.png", path)
        if m:
            run_id = m.group(1)
            if not pipeline.episode_dir(run_id, 1).exists() and nh.is_run(run_id):
                final = nh.final_episode(run_id)
                if not final:
                    return self._error(404, "아직입니다")
                src = watermark.for_download(
                    final, nh.run_dir(run_id), nh.episode_caption(run_id),
                    cut_bounds=nh.page_bounds(run_id))
                return self._file(src, download=f"{run_id}.png")
            ep = self._ep(query)
            ep_dir = pipeline.episode_dir(m.group(1), ep)
            # 내려받는 것도 **최종본**이다 — 편집실에서 얹은 것이 있으면 구운
            # 판, 없으면 원본 그대로. 얹어 놓고 내려받았더니 말풍선이 없더라는
            # 것이 가장 알아채기 어려운 실패다.
            # 나가는 파일에만 LORE 표시를 얹는다 (watermark.py 머리말 참고).
            final = pipeline.final_episode(m.group(1), ep)
            bounds = pipeline.cut_bounds(
                m.group(1), ep, baked=(final == overlay.baked_episode_path(ep_dir)))
            src = watermark.for_download(
                final, ep_dir, pipeline.episode_caption(m.group(1), ep),
                cut_bounds=bounds)
            return self._file(src, download=pipeline.episode_filename(m.group(1), ep))

        # 편집실에서 얹은 말풍선·스티커. 브라우저가 아니라 **작품 폴더**에 있어서
        # 다른 기기에서 열어도 그대로다.
        m = re.fullmatch(r"/api/runs/([\w.-]+)/overlay", path)
        if m:
            run_id = m.group(1)
            if not pipeline.episode_dir(run_id, 1).exists() and nh.is_run(run_id):
                return self._json(nh.read_overlay(run_id))
            return self._json(pipeline.read_overlay(run_id, self._ep(query)))

        # 구워 놓은 한 편 내려받기. 아직 안 구웠으면 404 — 화면이 "먼저 구우세요"
        # 라고 말할 수 있어야 하므로 원본으로 슬쩍 바꿔치지 않는다.
        m = re.fullmatch(r"/api/runs/([\w.-]+)/baked\.png", path)
        if m:
            ep = self._ep(query)
            src = pipeline.baked_episode(m.group(1), ep)
            if not src:
                return self._error(404, "아직 구운 그림이 없습니다")
            bounds = pipeline.cut_bounds(m.group(1), ep, baked=True)
            src = watermark.for_download(
                src, pipeline.episode_dir(m.group(1), ep),
                pipeline.episode_caption(m.group(1), ep), cut_bounds=bounds)
            return self._file(src, download=pipeline.episode_filename(
                m.group(1), ep, baked=True))

        m = re.fullmatch(r"/api/runs/([\w.-]+)/cost", path)
        if m:
            return self._json(pipeline.run_cost(m.group(1)))

        # 이 작품에 지금까지 어떤 말을 했는가. 화면이 "적어 주신 것" 목록을
        # 그리는 데 쓰고, 사람이 직접 열어 봐도 된다 (runs/<id>/feedback.jsonl).
        # 작가 규칙 — 작품마다 하나. 승인 화면·결과 화면의 편집칸이 읽는다.
        m = re.fullmatch(r"/api/runs/([\w.-]+)/memory", path)
        if m:
            return self._json(pipeline.read_memory(m.group(1)))

        m = re.fullmatch(r"/api/runs/([\w.-]+)/feedback", path)
        if m:
            return self._json({"feedback": pipeline.read_feedback(m.group(1))})

        # 그림 QA 최종 판정 — 검수가 잡았지만 재생성 한도 안에서 못 고친 것.
        # 결과 화면이 장 밑에 표시하고 "다시 그리기"(사용자 피드백)로 잇는다.
        m = re.fullmatch(r"/api/runs/([\w.-]+)/art-qa", path)
        if m:
            return self._json({"scenes": pipeline.read_art_qa(
                m.group(1), self._ep(query))})

        # 다시 그리기 — 지난 판 목록과 그 그림.
        m = re.fullmatch(r"/api/runs/([\w.-]+)/scenes/(\d+)/versions", path)
        if m:
            return self._json({"versions": pipeline.scene_versions(
                m.group(1), int(m.group(2)), self._ep(query))})

        m = re.fullmatch(r"/api/runs/([\w.-]+)/scenes/(\d+)/versions/(\d+)", path)
        if m:
            ep = self._ep(query)
            src = pipeline.version_path(m.group(1), int(m.group(2)),
                                        int(m.group(3)), ep)
            if not src:
                return self._error(404, "그 판본이 없습니다")
            width = max(160, min(1400, int((query.get("w") or ["1080"])[0])))
            dest = (pipeline.episode_dir(m.group(1), ep) / "cache"
                    / f"v{m.group(2)}_{m.group(3)}_w{width}.jpg")
            try:
                return self._file(thumbnail(src, dest, width))
            except Exception:                                   # noqa: BLE001
                return self._file(src)

        # 존(배경) 목록. **이미지가 아니라 글이다** — 어떤 자리가 있고 그 서술이
        # 어디에 쓰이는지만 보여 준다. 틀린 곳은 series.json 한 줄을 고친다.
        m = re.fullmatch(r"/api/runs/([\w.-]+)/zones", path)
        if m:
            return self._json({"zones": pipeline.zone_list(m.group(1))})

        m = re.fullmatch(r"/api/regens/([\w.-]+)", path)
        if m:
            job = pipeline.regens.get(m.group(1))
            if not job:
                return self._error(404, "그런 작업이 없습니다")
            return self._json(job.snapshot())

        m = re.fullmatch(r"/api/runs/([\w.-]+)/page/(\d+)", path)
        if m and not pipeline.episode_dir(m.group(1), 1).exists() and nh.is_run(m.group(1)):
            run_id = m.group(1)
            raw = (query.get("raw") or [""])[0] == "1"
            no = int(m.group(2))
            src = nh.unit_image(run_id, no) if raw else nh.final_unit(run_id, no)
            if not src:
                return self._error(404, "그 장의 그림이 없습니다")
            width = max(160, min(1400, int((query.get("w") or ["1080"])[0])))
            stamp = int(src.stat().st_mtime)
            head = f"page{no}{'_raw' if raw else ''}_w{width}"
            cache = nh.run_dir(run_id) / "cache"
            dest = cache / f"{head}_{stamp}.jpg"
            for old_file in cache.glob(f"{head}_*.jpg"):
                if old_file != dest:
                    try:
                        old_file.unlink()
                    except OSError:
                        pass
            try:
                return self._file(thumbnail(src, dest, width))
            except Exception:                                   # noqa: BLE001
                return self._file(src)
        if m:
            ep = self._ep(query)
            # 기본은 **최종본** — 편집실에서 얹은 것이 구워진 그림이다. 결과
            # 화면·둘러보기·마이페이지가 전부 이 주소를 쓰므로, 여기 하나만
            # 최종본을 가리키면 보는 자리가 다 같이 맞는다.
            #
            # `raw=1` 은 편집실 전용이다. 편집실은 얹은 것을 DOM 으로 따로
            # 그리므로 밑그림에까지 구워져 있으면 말풍선이 두 겹으로 보인다.
            raw = (query.get("raw") or [""])[0] == "1"
            no = int(m.group(2))
            src = (pipeline.unit_image(m.group(1), no, ep) if raw
                   else pipeline.final_unit(m.group(1), no, ep))
            if not src:
                return self._error(404, "그 장의 그림이 없습니다")
            width = max(160, min(1400, int((query.get("w") or ["1080"])[0])))
            # 줄여 둔 것의 이름에 **밑그림의 시각**을 넣는다. 이름이 고정이면,
            # 얹은 것을 다 지워 원본으로 돌아갔을 때 캐시가 더 새것이라
            # 지워진 말풍선이 계속 보인다(thumbnail 이 mtime 만 비교한다).
            stamp = int(src.stat().st_mtime)
            head = f"page{m.group(2)}{'_raw' if raw else ''}_w{width}"
            cache = pipeline.episode_dir(m.group(1), ep) / "cache"
            dest = cache / f"{head}_{stamp}.jpg"
            # 같은 장·같은 크기의 지난 캐시는 지운다 — 안 지우면 고칠 때마다
            # 파일이 하나씩 쌓인다.
            for old_file in cache.glob(f"{head}_*.jpg"):
                if old_file != dest:
                    try:
                        old_file.unlink()
                    except OSError:
                        pass
            try:
                return self._file(thumbnail(src, dest, width))
            except Exception:                                   # noqa: BLE001
                return self._file(src)

        if path == "/api/latest":
            # 가장 최근에 **끝난** 작업. /result 가 이걸 보고 결과를 띄운다.
            done = [j for j in runner.jobs.values() if j.status == "done" and j.run_id]
            if not done:
                return self._error(404, "아직 완성된 작품이 없습니다")
            newest = max(done, key=lambda j: j.finished_at or 0)
            return self._json({"id": newest.id, "run_id": newest.run_id})

        m = re.fullmatch(r"/api/jobs/([\w.-]+)", path)
        if m:
            job = runner.get(m.group(1))
            if not job:
                return self._error(404, "그런 작업이 없습니다")
            state = job.snapshot()
            state["queue_position"] = runner.position(job.id)
            return self._json(state)

        m = re.fullmatch(r"/api/jobs/([\w.-]+)/result", path)
        if m:
            job = runner.get(m.group(1))
            if not job:
                return self._error(404, "그런 작업이 없습니다")
            return self._json(pipeline.result(job))

        # 장(Scene) 하나 = 이미지 하나. 한 장에 컷이 3개 들어 있다.
        m = re.fullmatch(r"/api/jobs/([\w.-]+)/page/(\d+)", path)
        if m:
            job = runner.get(m.group(1))
            if not job or not job.run_id:
                return self._error(404, "아직입니다")
            # job.episode 를 꼭 넘긴다 — 안 넘기면 ep1 로 떨어져서, 2화 작업의
            # 결과 화면이 1화 그림을 보여 준다 (내려받기는 #64 에서 같은 이유로
            # 이미 회차를 따라가게 고쳤는데 이 자리가 빠져 있었다).
            src = pipeline.unit_image(job.run_id, int(m.group(2)), job.episode)
            if not src:
                return self._error(404, "아직입니다")
            width = max(160, min(1400, int((query.get("w") or ["1080"])[0])))
            # 캐시 열쇠에도 회차를 넣는다 — 같은 job 폴더에서 1화 캐시가 2화
            # 이름을 차지하면 위 수정이 무효가 된다.
            dest = job.dir / "cache" / f"ep{job.episode}_page{m.group(2)}_w{width}.jpg"
            try:
                return self._file(thumbnail(src, dest, width))
            except Exception:                                   # noqa: BLE001
                return self._file(src)

        m = re.fullmatch(r"/api/jobs/([\w.-]+)/sheet", path)
        if m:
            job = runner.get(m.group(1))
            if not job or not job.run_id:
                return self._error(404, "아직입니다")
            src = pipeline.STORY / "runs" / job.run_id / "charsheet" / "sheet_c1.png"
            if not src.exists():
                return self._error(404, "아직입니다")
            dest = job.dir / "cache" / "sheet_w720.jpg"
            try:
                return self._file(thumbnail(src, dest, 720))
            except Exception:                                   # noqa: BLE001
                return self._file(src)

        # 시트 승인 화면에서 원본 참조 사진과 나란히 보여줄 자리.
        m = re.fullmatch(r"/api/jobs/([\w.-]+)/photo(?:/(\d+))?", path)
        if m:
            job = runner.get(m.group(1))
            if not job or not job.has_photo:
                return self._error(404, "업로드한 사진이 없습니다")
            shots = pipeline.job_photos(job.dir)
            if not shots:
                return self._error(404, "업로드한 사진이 없습니다")
            idx = int(m.group(2) or 1)
            if not 1 <= idx <= len(shots):
                return self._error(404, "그 번호의 사진이 없습니다")
            return self._file(shots[idx - 1])

        # 몇 장이 올라왔는지 — 시트 승인 화면이 몇 칸을 그릴지 정하는 데 쓴다.
        m = re.fullmatch(r"/api/jobs/([\w.-]+)/photos", path)
        if m:
            job = runner.get(m.group(1))
            if not job:
                return self._error(404, "그런 작업이 없습니다")
            n = len(pipeline.job_photos(job.dir))
            return self._json({"count": n,
                               "urls": [f"/api/jobs/{job.id}/photo/{i}"
                                        for i in range(1, n + 1)]})

        # 시트 승인 화면의 수정 폼에 채워 줄 현재 값 (name/appearance_en/design_details).
        m = re.fullmatch(r"/api/jobs/([\w.-]+)/sheet-fields", path)
        if m:
            job = runner.get(m.group(1))
            if not job or not job.run_id:
                return self._error(404, "아직입니다")
            return self._json(pipeline.sheet_fields(job.run_id))

        m = re.fullmatch(r"/api/jobs/([\w.-]+)/episode\.png", path)
        if m:
            job = runner.get(m.group(1))
            if not job or not job.run_id:
                return self._error(404, "아직입니다")
            # 회차를 무시하면 2화 작업이 1화 파일을 내려받는다 — episode_dir 의
            # 기본값이 ep1 이라 조용히 틀린 파일이 나간다.
            ep_dir = pipeline.episode_dir(job.run_id, job.episode)
            src = watermark.for_download(
                ep_dir / "episode.png", ep_dir,
                pipeline.episode_caption(job.run_id, job.episode))
            return self._file(src, download=pipeline.episode_filename(
                job.run_id, job.episode))

        # ---- new_harness 실험 경로 ------------------------------------------ #

        m = re.fullmatch(r"/api/nh/jobs/([\w.-]+)", path)
        if m:
            job = nh_runner.get(m.group(1))
            if not job:
                return self._error(404, "그런 작업이 없습니다")
            return self._json({**job.snapshot(),
                               "queue_position": nh_runner.position(job.id)})

        # 완성본 — 편집실에서 얹은 것이 있으면 구운 판(final_episode)이 나간다.
        # /nh 는 컷 단위 읽기 화면이 없이 이 그림 하나가 곧 "가져가는 것"이라
        # (classic 의 낱장 읽기와 다르게), 여기도 워터마크를 찍는다.
        m = re.fullmatch(r"/api/nh/jobs/([\w.-]+)/episode\.png", path)
        if m:
            job = nh_runner.get(m.group(1))
            if not job or not job.run_id:
                return self._error(404, "그런 작업이 없습니다")
            final = nh.final_episode(job.run_id)
            if not final:
                return self._error(404, "아직입니다")
            src = watermark.for_download(
                final, nh.run_dir(job.run_id), nh.episode_caption(job.run_id),
                cut_bounds=nh.page_bounds(job.run_id))
            return self._file(src)

        m = re.fullmatch(r"/api/nh/jobs/([\w.-]+)/sheet\.png", path)
        if m:
            job = nh_runner.get(m.group(1))
            if not job:
                return self._error(404, "그런 작업이 없습니다")
            src = nh.sheet_path(job)
            if not src:
                return self._error(404, "아직입니다")
            return self._file(src)

        # job 기준 페이지 한 장. `raw=1` 이면 편집실 전용(원본, 안 구움).
        m = re.fullmatch(r"/api/nh/jobs/([\w.-]+)/page/(\d+)\.png", path)
        if m:
            job = nh_runner.get(m.group(1))
            if not job or not job.run_id:
                return self._error(404, "그런 작업이 없습니다")
            raw = (query.get("raw") or [""])[0] == "1"
            no = int(m.group(2))
            src = (nh.unit_image(job.run_id, no) if raw
                   else nh.final_unit(job.run_id, no))
            if not src:
                return self._error(404, "아직입니다")
            width = max(160, min(1400, int((query.get("w") or ["1080"])[0])))
            dest = job.dir / "cache" / f"page{no}{'_raw' if raw else ''}_w{width}.jpg"
            try:
                return self._file(thumbnail(src, dest, width))
            except Exception:                                   # noqa: BLE001
                return self._file(src)

        # ---- run_id 로 직접 여는 편집실 (job 없이도, 완성된 뒤에도) --------- #

        m = re.fullmatch(r"/api/nh/runs/([\w.-]+)/pages", path)
        if m:
            return self._json({"pages": nh.page_numbers(m.group(1))})

        m = re.fullmatch(r"/api/nh/runs/([\w.-]+)/overlay", path)
        if m:
            return self._json(nh.read_overlay(m.group(1)))

        m = re.fullmatch(r"/api/nh/runs/([\w.-]+)/episode\.png", path)
        if m:
            run_id = m.group(1)
            final = nh.final_episode(run_id)
            if not final:
                return self._error(404, "아직입니다")
            src = watermark.for_download(
                final, nh.run_dir(run_id), nh.episode_caption(run_id),
                cut_bounds=nh.page_bounds(run_id))
            return self._file(src)

        m = re.fullmatch(r"/api/nh/runs/([\w.-]+)/page/(\d+)", path)
        if m:
            raw = (query.get("raw") or [""])[0] == "1"
            run_id, no = m.group(1), int(m.group(2))
            src = nh.unit_image(run_id, no) if raw else nh.final_unit(run_id, no)
            if not src:
                return self._error(404, "그 페이지가 없습니다")
            width = max(160, min(1400, int((query.get("w") or ["1080"])[0])))
            stamp = int(src.stat().st_mtime)
            cache = nh.run_dir(run_id) / "cache"
            dest = cache / f"page{no}{'_raw' if raw else ''}_w{width}_{stamp}.jpg"
            for old_file in cache.glob(f"page{no}{'_raw' if raw else ''}_w{width}_*.jpg"):
                if old_file != dest:
                    try:
                        old_file.unlink()
                    except OSError:
                        pass
            try:
                return self._file(thumbnail(src, dest, width))
            except Exception:                                   # noqa: BLE001
                return self._file(src)

        m = re.fullmatch(r"/api/nh/regens/([\w.-]+)", path)
        if m:
            try:
                return self._json(nh_runner.regen_status(m.group(1)))
            except KeyError:
                return self._error(404, "그런 작업이 없습니다")

        return self._error(404, "없는 주소입니다")

    def do_POST(self) -> None:                                  # noqa: N802
        url = urlparse(self.path)

        # ---- 계정(선택 기능) ------------------------------------------------ #
        if url.path == "/api/account/signup":
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._error(400, "입력을 읽지 못했습니다")
            account, err = accounts.signup(str(body.get("nickname") or ""),
                                           str(body.get("password") or ""),
                                           body.get("photo"),
                                           bool(body.get("agree_terms")))
            if err:
                return self._error(400, err)
            token = accounts.create_session(account["key"])
            return self._json({"logged_in": True, **account},
                              headers=self._set_session_header(token))

        if url.path == "/api/account/login":
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._error(400, "입력을 읽지 못했습니다")
            account, err = accounts.verify_password(str(body.get("nickname") or ""),
                                                     str(body.get("password") or ""))
            if err:
                return self._error(401, err)
            token = accounts.create_session(account["key"])
            return self._json({"logged_in": True, **account},
                              headers=self._set_session_header(token))

        if url.path == "/api/account/logout":
            accounts.destroy_session(self._session_cookie())
            return self._json({"ok": True}, headers=self._clear_session_header())

        if url.path == "/api/account/photo":
            key = self._account_key()
            if not key:
                return self._error(401, "로그인이 필요합니다")
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._error(400, "입력을 읽지 못했습니다")
            ok, err = accounts.set_photo(key, body.get("photo") or {})
            if not ok:
                return self._error(400, err)
            account = accounts.get_account(key)
            return self._json({"logged_in": True, **accounts.public_info(key, account)})

        # 결과 화면의 "계정에 담아두기". 로그인이 안 돼 있으면 여기서 막고,
        # 화면이 그 응답을 보고 로그인/회원가입 모달을 연다.
        if url.path == "/api/account/claim":
            key = self._account_key()
            if not key:
                return self._error(401, "로그인이 필요합니다")
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._error(400, "입력을 읽지 못했습니다")
            run_id = str(body.get("run_id") or "")
            if not re.fullmatch(r"[\w.-]+", run_id):
                return self._error(400, "run_id 가 없습니다")
            # 주소만 알면 남의 작품도 담을 수 있었다. 담고 나면 그 작품의 공개
            # 여부까지 바꿀 수 있으므로(visibility 가 claimed_runs 를 믿는다),
            # 남이 올린 작품을 아무나 둘러보기에서 내릴 수 있다는 뜻이었다.
            holder = accounts.claimed_by(run_id)
            if holder == key:
                return self._json({"ok": True})       # 이미 내 것 — 조용히 넘어간다
            ok, why = ownership.may_claim(run_id, str(body.get("uid") or ""), holder)
            if not ok:
                return self._error(403, why)
            accounts.claim_run(key, run_id)
            return self._json({"ok": True})

        # ---- 크레딧 · 프리토타이핑 결제 ----------------------------------- #
        #
        # "충전하기" 를 누른 순간(카드 고르기 전)과, 카드사를 골라 결제를
        # 끝낸 순간을 따로 기록한다 — 이 둘의 차이가 "몇 명이 눌렀는데 몇
        # 명이 실제로 끝까지 갔는가"(클릭률)다.
        if url.path == "/api/credits/charge-click":
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                body = {}
            uid = str(body.get("uid") or "")
            if not credits.valid_uid(uid):
                return self._error(400, "uid 가 없습니다")
            credits.log_event("charge_click", uid)
            return self._json({"ok": True})

        if url.path == "/api/credits/charge":
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._error(400, "입력을 읽지 못했습니다")
            uid = str(body.get("uid") or "")
            if not credits.valid_uid(uid):
                return self._error(400, "uid 가 없습니다")
            package_id = str(body.get("package_id") or "")
            pkg, bal = credits.charge(uid, package_id)
            if not pkg:
                return self._error(400, "그런 상품이 없습니다")
            # 카드사를 고른 것 = 결제를 끝낸 것(가짜 결제라 카드번호 입력은
            # 없다). 실제 PG 응답이 아니라 여기서 바로 지급하고 로그를 남긴다.
            credits.log_event("charge_success", uid, package_id=package_id,
                              credits=pkg["credits"], price=pkg["price"])
            return self._json({"balance": bal, "credits_added": pkg["credits"],
                               "package": pkg})

        # 하루 1회 무료 크레딧 지급. 오늘 이미 받았으면 granted:false 로
        # 답한다 — 그것도 정상 응답이라 400 이 아니다(화면이 "내일 다시" 로
        # 바꿔 보여주면 된다).
        if url.path == "/api/credits/daily":
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                body = {}
            uid = str(body.get("uid") or "")
            if not credits.valid_uid(uid):
                return self._error(400, "uid 가 없습니다")
            result = credits.claim_daily(uid)
            if result["granted"]:
                credits.log_event("daily_claim", uid,
                                  credits=result["credits_added"])
            return self._json(result)

        # 작가 규칙 저장. 상한을 넘으면 자르지 않고 거절한다 — 화면이 그 오류를
        # 그대로 보여줘야 작가가 자기 글이 어디까지 실리는지 안다.
        m = re.fullmatch(r"/api/runs/([\w.-]+)/memory", url.path)
        if m:
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._error(400, "입력을 읽지 못했습니다")
            cleaned, err = pipeline.write_memory(m.group(1), body or {})
            if err:
                return self._error(400, err)
            return self._json(cleaned)

        if url.path == "/api/create":
            try:
                form = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._error(400, "입력을 읽지 못했습니다")

            # 사진은 여러 장 올 수 있다 — 한 사람을 여러 각도로 찍은 것이다.
            # 한 장으로는 늘 안 보이는 칸(하의·신발·뒤통수)이 남고, 다른 각도가
            # 그 칸을 채운다. 옛 화면은 photo_data 하나만 보내므로 둘 다 받는다.
            urls = form.pop("photos_data", None)
            if not isinstance(urls, list):
                urls = []
            single = str(form.pop("photo_data", "") or "")
            if single:
                urls.insert(0, single)
            urls = [u for u in urls if str(u or "").startswith("data:")]
            if len(urls) > pipeline.MAX_PHOTOS:
                return self._error(400,
                                   f"사진은 {pipeline.MAX_PHOTOS}장까지 올릴 수 있습니다")

            photos = []
            for i, data_url in enumerate(urls, 1):
                try:
                    raw = base64.b64decode(data_url.split(",", 1)[1])
                except (ValueError, IndexError):
                    return self._error(400, f"{i}번째 사진을 읽지 못했습니다")
                if len(raw) > MAX_PHOTO_BYTES:
                    return self._error(400, f"{i}번째 사진이 너무 큽니다 (6MB 까지)")
                # Pillow 가 없는 것과 사진이 이상한 것을 **따로** 잡는다.
                # 한 덩이로 잡으면 라이브러리가 없을 때도 "사진 형식을 알 수
                # 없습니다" 가 나가서, 멀쩡한 사진을 올린 사람이 사진만 계속
                # 바꿔 보게 된다 (실제로 그렇게 헤맸다). 하네스의 strip.py ·
                # episode.py 는 처음부터 ImportError 를 따로 잡고 있었다 —
                # 여기만 빠져 있었다.
                try:
                    from PIL import Image
                except ImportError:
                    return self._error(
                        500, "서버에 Pillow 가 없어 사진을 처리하지 못합니다. "
                             "pip install Pillow 로 설치한 뒤 서버를 다시 켜 주세요. "
                             "(사진 없이 만드시려면 올린 사진을 지우고 진행하세요.)")
                try:
                    im = Image.open(io.BytesIO(raw))
                    im.load()
                    if im.width > 1400:
                        h = round(im.height * 1400 / im.width)
                        im = im.resize((1400, h), Image.LANCZOS)
                    buf = io.BytesIO()
                    im.convert("RGB").save(buf, "PNG")
                    photos.append(buf.getvalue())
                except Exception:                               # noqa: BLE001
                    # 아이폰 기본 설정이 HEIC 라서 이 자리에 가장 많이 걸린다.
                    # Pillow 는 HEIC 를 기본으로 못 읽는다.
                    return self._error(
                        400, f"{i}번째 사진을 열지 못했습니다. 아이폰 사진(HEIC)이면 "
                             "JPG 나 PNG 로 바꿔서 올려 주세요.")
            photo = photos

            # 캐릭터를 알 수 있는 것이 하나는 있어야 한다 — story.py 가 그렇게
            # 요구하고, 그 이유가 맞다. 아무것도 없으면 모델이 인물을 통째로
            # 지어내고 그건 사용자의 캐릭터가 아니다.
            known = any(str(form.get(k) or "").strip()
                        for k in ("name", "character")) or \
                any(str(v or "").strip() for v in (form.get("fields") or {}).values()) \
                or bool(photos)
            if not known:
                return self._error(400, "캐릭터를 알 수 있는 것이 하나는 필요합니다 — "
                                        "이름 · 설명 · 항목 · 사진 중 아무거나요.")

            # 저작권 확인 — 회원가입 때 약관 동의(accounts.signup)와 별개로,
            # 만들 때마다 짧게 다시 받는다. 로그인 여부와 무관하게 게스트도
            # 걸린다(uid 는 있으므로).
            if not form.pop("agree_ip", False):
                return self._error(400, "저작권 확인에 동의해야 만들 수 있습니다")

            # 크레딧 소진 — 화면의 비용 표시(costChip)와 같은 계산이다
            # (credits.creation_cost). 잔액은 미리 확인만 하고, 실제로 떼는
            # 것은 job 이 만들어진 **뒤**다 — job 생성이 실패했는데 이미
            # 크레딧부터 떼면(환불 기능은 범위 밖이라) 사용자가 그냥 잃는다.
            uid = str(form.pop("uid", "") or "")
            if not credits.valid_uid(uid):
                return self._error(400, "uid 가 없습니다")
            cost = credits.creation_cost(bool(form.get("preview")),
                                         str(form.get("layout_mode") or "fast"))
            bal = credits.balance(uid)
            if bal < cost:
                return self._error(
                    402, f"크레딧이 모자랍니다 (필요 {cost} · 보유 {bal})",
                    reason="insufficient_credit", need=cost, balance=bal)

            job = runner.create(form, photo)
            _, bal = credits.spend(uid, cost)
            credits.log_event("spend", uid, amount=cost, balance=bal,
                              job_id=job.id, reason="create")
            accounts.log_ip_consent(uid, job.id)
            return self._json({"id": job.id, "queue_position": runner.position(job.id),
                               "credit_balance": bal})

        # ---- 장(Scene) 다시 그리기 ------------------------------------- #
        #
        # 크레딧 차감은 없다 (#16 이 백로그라 붙일 곳이 없다). 실제 API 비용은
        # 나가므로, 화면이 "몇 크레딧" 이라고 적어 두더라도 그건 목업이다.
        m = re.fullmatch(r"/api/runs/([\w.-]+)/scenes/(\d+)/regen", url.path)
        if m:
            run_id, scene_no = m.group(1), int(m.group(2))
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                body = {}
            ep = self._ep({**parse_qs(url.query),
                           **({"ep": [str(body["episode"])]} if body.get("episode")
                              else {})})
            if not pipeline.scene_cut_range(run_id, scene_no, ep):
                return self._error(404, "그 장을 찾지 못했습니다")
            if not pipeline.unit_image(run_id, scene_no, ep):
                return self._error(409, "아직 그려지지 않은 장입니다")
            # 이 작품을 본 파이프라인이 그리는 중이면 막는다 — regen 과 run.py 가
            # 같은 ep 폴더의 scenes.json·episode.png 를 동시에 쓰면 서로를
            # 덮어쓴다. next-episode 의 가드와 같은 이유, 같은 기준이다.
            busy = [j for j in runner.jobs.values()
                    if j.run_id == run_id and j.status in
                    ("queued", "running", "awaiting_board_approval",
                     "awaiting_story_approval", "awaiting_sheet_approval")]
            if busy:
                return self._error(409, "이 작품은 지금 만드는 중입니다 — "
                                        "끝난 뒤 다시 그려 주세요")
            feedback = str(body.get("feedback") or "").strip()
            if len(feedback) > pipeline.FEEDBACK_TEXT_MAX:
                return self._error(
                    400, f"요청은 {pipeline.FEEDBACK_TEXT_MAX}자까지 적어 주세요")
            job = pipeline.regens.start(run_id, scene_no, feedback,
                                        str(body.get("style") or ""),
                                        bool(body.get("textless")),
                                        pipeline.clean_tags("scene", body.get("tags")),
                                        ep)
            return self._json(job.snapshot())

        m = re.fullmatch(r"/api/regens/([\w.-]+)/cancel", url.path)
        if m:
            job = pipeline.regens.get(m.group(1))
            if not job:
                return self._error(404, "그런 작업이 없습니다")
            job.cancel()
            return self._json({"ok": True})

        # 지난 판으로 되돌리기. 되돌리기 직전 그림도 판본으로 남으므로
        # "되돌린 것을 다시 되돌리기" 도 된다.
        m = re.fullmatch(r"/api/runs/([\w.-]+)/scenes/(\d+)/revert", url.path)
        if m:
            run_id, scene_no = m.group(1), int(m.group(2))
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._error(400, "입력을 읽지 못했습니다")
            try:
                version = int(body.get("version"))
            except (TypeError, ValueError):
                return self._error(400, "version 이 필요합니다")
            ep = self._ep({**parse_qs(url.query),
                           **({"ep": [str(body["episode"])]} if body.get("episode")
                              else {})})
            if not pipeline.revert_scene(run_id, scene_no, version, ep):
                return self._error(404, "그 판본으로 되돌리지 못했습니다")
            return self._json({"ok": True,
                               "versions": pipeline.scene_versions(run_id, scene_no, ep)})

        # ---- 둘러보기에 걸지 말지 ---------------------------------------- #
        #
        # 내 작품만 바꿀 수 있다. "내 것" 의 근거는 계정에 담아둔 목록
        # (claimed_runs)이다 — 로그인 안 한 채로 만든 작품은 담아 두기 전까지
        # 주인이 없어서, 아무나 남의 작품을 내릴 수 있게 두지 않으려면 여기서
        # 막아야 한다.
        m = re.fullmatch(r"/api/runs/([\w.-]+)/visibility", url.path)
        if m:
            run_id = m.group(1)
            key = self._account_key()
            if not key:
                return self._error(401, "로그인이 필요합니다")
            account = accounts.get_account(key)
            if run_id not in set((account or {}).get("claimed_runs", [])):
                return self._error(403, "내 계정에 담아둔 작품만 바꿀 수 있습니다")
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                body = {}
            public = bool(body.get("public"))
            visibility.set_public(run_id, public)
            return self._json({"run_id": run_id, "public": public})

        # ---- 다음 화 이어서 만들기 (#72) -------------------------------- #
        #
        # 이야기·캐릭터 시트는 안 돈다 — 1화 것을 그대로 쓴다. 콘티부터 시작해서
        # 그림·잇기까지 간다. 회차 번호는 서버가 정한다(스토리 하네스의 next_no)
        # — 화면이 보내는 번호를 믿으면 두 창에서 동시에 눌렀을 때 같은 번호를
        # 두 번 만들려 든다.
        m = re.fullmatch(r"/api/runs/([\w.-]+)/next-episode", url.path)
        if m:
            run_id = m.group(1)
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                body = {}
            if not pipeline.made_episodes(run_id):
                return self._error(404, "1화 콘티가 없는 작품입니다")
            # 같은 작품을 동시에 두 번 이어 만들면 회차가 꼬인다.
            busy = [j for j in runner.jobs.values()
                    if j.run_id == run_id and j.status in
                    ("queued", "running", "awaiting_board_approval",
                     "awaiting_story_approval", "awaiting_sheet_approval")]
            if busy:
                return self._error(409, "이 작품은 지금 만드는 중입니다")
            note = str(body.get("author_note") or "").strip()
            if len(note) > pipeline.FEEDBACK_TEXT_MAX:
                return self._error(
                    400, f"요청은 {pipeline.FEEDBACK_TEXT_MAX}자까지 적어 주세요")
            # 다음 화는 한 화를 통째로 그린다(미리보기 없음) — 한 편 값이다.
            # /continue 와 같은 이유로, 이 자리에 차감이 없어서 2화부터는
            # 전부 공짜였다. uid 가 없으면 막지 않는 것도 같은 기준이다.
            uid = str(body.get("uid") or "")
            cost = 0
            if credits.valid_uid(uid):
                layout = str((pipeline.origin_form(run_id) or {})
                             .get("layout_mode") or "fast")
                cost = credits.creation_cost(False, layout)
                bal = credits.balance(uid)
                if bal < cost:
                    return self._error(
                        402, f"크레딧이 모자랍니다 (필요 {cost} · 보유 {bal})",
                        reason="insufficient_credit", need=cost, balance=bal)
            try:
                job = runner.create_next(run_id, {"author_note": note} if note else {})
            except pipeline.Failed as exc:
                return self._error(409, str(exc))
            bal = None
            if cost:
                bal = credits.spend(uid, cost)[1]
                credits.log_event("spend", uid, amount=cost, balance=bal,
                                  job_id=job.id, reason="next_episode")
            return self._json({"id": job.id, "episode": job.episode,
                               "queue_position": runner.position(job.id),
                               **({"credit_balance": bal} if bal is not None else {})})

        # 이어 그리기 — 미리보기로 앞 3컷을 본 뒤 "다음 장면도 볼까요?".
        # 회차는 안 늘어나고 콘티도 안 만든다. 다음 3컷을 그리고 다시 잇는다.
        m = re.fullmatch(r"/api/runs/([\w.-]+)/continue", url.path)
        if m:
            run_id = m.group(1)
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                body = {}
            episode = int(body.get("episode") or 1)
            drawn = pipeline.drawn_units(run_id, episode)
            if not drawn:
                return self._error(404, "아직 그린 장면이 없습니다")
            total = pipeline.planned_cuts(run_id, episode)
            cut_from = drawn * pipeline.CUTS_PER_SHEET + 1
            if total and cut_from > total:
                return self._error(409, "더 그릴 장면이 없습니다")
            busy = [j for j in runner.jobs.values()
                    if j.run_id == run_id and j.status in
                    ("queued", "running", "awaiting_board_approval",
                     "awaiting_story_approval", "awaiting_sheet_approval")]
            if busy:
                return self._error(409, "이 작품은 지금 만드는 중입니다")
            # **여기서는 안 받는다.** 한 편 값(12C)은 만들 때 전액 받았고,
            # 이 자리는 이미 산 웹툰의 나머지를 마저 그리는 것뿐이다 —
            # 미리보기가 마음에 든 순간 결제 버튼을 또 누르게 하면 구매
            # 흐름이 거기서 끊긴다.
            try:
                job = runner.create_more(run_id, cut_from)
            except pipeline.Failed as exc:
                return self._error(409, str(exc))
            return self._json({"id": job.id, "cut_from": cut_from,
                               "queue_position": runner.position(job.id)})

        m = re.fullmatch(r"/api/jobs/([\w.-]+)/cancel", url.path)
        if m:
            job = runner.get(m.group(1))
            if not job:
                return self._error(404, "그런 작업이 없습니다")
            job.cancel()
            return self._json({"ok": True})

        # 시트 승인 화면의 "이대로 진행" / "다시 만들기" 버튼.
        m = re.fullmatch(r"/api/jobs/([\w.-]+)/sheet-decision", url.path)
        if m:
            job = runner.get(m.group(1))
            if not job:
                return self._error(404, "그런 작업이 없습니다")
            if job.status != "awaiting_sheet_approval":
                return self._error(409, "지금은 시트 확인 단계가 아닙니다")
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._error(400, "입력을 읽지 못했습니다")
            decision = str(body.get("decision") or "")
            if decision not in ("approve", "retry"):
                return self._error(400, "decision 은 approve 또는 retry 여야 합니다")
            fields = body.get("fields")
            fields = fields if isinstance(fields, dict) else None
            self._record_feedback(job, "sheet", decision, body)
            # 고른 항목·적은 말을 기록만 하고 끝내지 않는다 — 지시문으로 옮겨
            # 다음 판 시트 프롬프트에 싣는다(pipeline.sheet_corrections).
            # 일반 모드에는 사양 수정 폼이 없어서, 이것이 사용자의 말이 그림에
            # 닿는 유일한 길이다.
            fixes = pipeline.sheet_corrections(
                pipeline.clean_tags("sheet", body.get("tags")),
                str(body.get("feedback") or ""))
            job.decide_sheet(decision, fields, fixes)
            return self._json({"ok": True})

        # 스토리 확인 화면의 "이대로 진행" / "다시 만들기" 버튼 — 스토리 단계
        # 게이트 재시도가 소진돼(STATUS_HUMAN) 사람 확인이 필요할 때만 뜬다.
        m = re.fullmatch(r"/api/jobs/([\w.-]+)/story-decision", url.path)
        if m:
            job = runner.get(m.group(1))
            if not job:
                return self._error(404, "그런 작업이 없습니다")
            if job.status != "awaiting_story_approval":
                return self._error(409, "지금은 스토리 확인 단계가 아닙니다")
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._error(400, "입력을 읽지 못했습니다")
            decision = str(body.get("decision") or "")
            if decision not in ("approve", "retry"):
                return self._error(400, "decision 은 approve 또는 retry 여야 합니다")
            job.decide_story(decision, self._record_feedback(job, "story", decision, body))
            return self._json({"ok": True})

        # 콘티 확인 화면의 "이대로 진행" / "다시 만들기" 버튼 — 콘티 단계
        # 게이트 재시도가 소진돼(STATUS_HUMAN) 사람 확인이 필요할 때만 뜬다.
        m = re.fullmatch(r"/api/jobs/([\w.-]+)/board-decision", url.path)
        if m:
            job = runner.get(m.group(1))
            if not job:
                return self._error(404, "그런 작업이 없습니다")
            if job.status != "awaiting_board_approval":
                return self._error(409, "지금은 콘티 확인 단계가 아닙니다")
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._error(400, "입력을 읽지 못했습니다")
            decision = str(body.get("decision") or "")
            if decision not in ("approve", "retry"):
                return self._error(400, "decision 은 approve 또는 retry 여야 합니다")
            job.decide_board(decision, self._record_feedback(job, "board", decision, body))
            return self._json({"ok": True})

        # 그림 검수 확인 화면의 "확인했습니다" 버튼 — 전문 모드에서만 뜬다.
        #
        # 앞의 셋과 달리 decision 을 안 받는다. 이 자리에는 되돌아갈 단계가
        # 없다(그림은 이미 다 나왔다) — 여기서 할 수 있는 일은 "봤다"뿐이고,
        # 실제로 고치는 것은 결과 화면의 장 단위 다시 그리기다. 고른 항목과
        # 적은 말은 다음 판을 고칠 근거로 남긴다.
        m = re.fullmatch(r"/api/jobs/([\w.-]+)/artqa-decision", url.path)
        if m:
            job = runner.get(m.group(1))
            if not job:
                return self._error(404, "그런 작업이 없습니다")
            if job.status != "awaiting_artqa_approval":
                return self._error(409, "지금은 그림 검수 확인 단계가 아닙니다")
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                body = {}
            self._record_feedback(job, "scene", "approve", body)
            job.decide_artqa()
            return self._json({"ok": True})

        # 회차 제목 고치기. 모델이 지은 이름이 늘 맞지는 않고, 공유가 붙은
        # 뒤로는 그 이름이 카톡·트위터 카드에 그대로 실린다.
        #
        # 빈 값을 보내면 지운다 — 모델이 지은 이름으로 되돌아간다. 그래서
        # DELETE 를 따로 두지 않는다(되돌리기가 곧 빈 제목이다).
        m = re.fullmatch(r"/api/runs/([\w.-]+)/title", url.path)
        if m:
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._error(400, "입력을 읽지 못했습니다")
            ep = self._ep({**parse_qs(url.query),
                           **({"ep": [str(body["episode"])]} if body.get("episode")
                              else {})})
            title = str(body.get("title") or "")
            if len(title) > pipeline.TITLE_MAX * 4:
                # 화면이 상한을 걸어 두지만 API 를 직접 부를 수도 있다. 자르기
                # 전에 터무니없이 큰 것은 아예 안 받는다.
                return self._error(400,
                                   f"제목은 {pipeline.TITLE_MAX}자까지 적어 주세요")
            run_id = m.group(1)
            # story-harness 에 없고 new_harness 에 있으면 그쪽에 저장한다 —
            # classic 의 set_user_title 은 story-harness/runs 아래에만 쓰므로
            # new_harness 작품은 제목을 고치면 404 가 났다(위 /episode·/result
            # 와 같은 누락이다).
            if not pipeline.episode_dir(run_id, 1).exists() and nh.is_run(run_id):
                try:
                    return self._json({"title": nh.set_user_title(run_id, title)})
                except (OSError, FileNotFoundError) as exc:
                    return self._error(404, str(exc))
            try:
                return self._json({"title": pipeline.set_user_title(
                    run_id, ep, title)})
            except pipeline.Failed as exc:
                return self._error(404, str(exc))

        # 편집실에서 얹은 것을 작품 폴더에 저장한다. 그림은 안 건드린다 —
        # 굽는 것은 아래 /bake 이고, 저장은 굽지 않아도 남아야 한다.
        m = re.fullmatch(r"/api/runs/([\w.-]+)/overlay", url.path)
        if m:
            run_id = m.group(1)
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._error(400, "입력을 읽지 못했습니다")
            if not pipeline.episode_dir(run_id, 1).exists() and nh.is_run(run_id):
                try:
                    return self._json(nh.write_overlay(run_id, body))
                except ValueError as exc:
                    return self._error(400, str(exc))
            ep = self._ep(parse_qs(url.query))
            try:
                return self._json(pipeline.write_overlay(run_id, body, ep))
            except pipeline.Failed as exc:
                return self._error(400, str(exc))

        # 얹은 것을 그림에 굽는다. 원본은 그대로 두고 baked/ 에 따로 쓴다 —
        # 말풍선을 옮긴 뒤 다시 구우려면 밑그림이 깨끗해야 한다.
        m = re.fullmatch(r"/api/runs/([\w.-]+)/bake", url.path)
        if m:
            run_id = m.group(1)
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                body = {}
            if not pipeline.episode_dir(run_id, 1).exists() and nh.is_run(run_id):
                try:
                    res = nh.bake_run(run_id, body)
                except ValueError as exc:
                    return self._error(400, str(exc))
                except overlay.OverlayError as exc:
                    return self._error(400, str(exc))
                res["url"] = f"/api/runs/{run_id}/episode.png"
                return self._json(res)
            ep = self._ep(parse_qs(url.query))
            try:
                return self._json(pipeline.bake_overlay(run_id, body, ep))
            except pipeline.Failed as exc:
                return self._error(400, str(exc))

        # ---- new_harness 실험 경로 ------------------------------------------ #
        #
        # /api/create 와 사진 처리 로직이 겹치지만 일부러 안 합친다 —
        # /api/create 는 실제 서비스 화면(lorecomic.com/webtoon)이 매 요청마다
        # 타는 자리라, 실험 경로를 고치다 실수로 거길 건드리는 위험을 아예
        # 없애는 쪽을 골랐다.

        if url.path == "/api/nh/create":
            try:
                form = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._error(400, "입력을 읽지 못했습니다")

            urls = form.pop("photos_data", None)
            urls = [u for u in urls if str(u or "").startswith("data:")] \
                if isinstance(urls, list) else []
            if len(urls) > pipeline.MAX_PHOTOS:
                return self._error(400,
                                   f"사진은 {pipeline.MAX_PHOTOS}장까지 올릴 수 있습니다")

            photos = []
            for i, data_url in enumerate(urls, 1):
                try:
                    raw = base64.b64decode(data_url.split(",", 1)[1])
                except (ValueError, IndexError):
                    return self._error(400, f"{i}번째 사진을 읽지 못했습니다")
                if len(raw) > MAX_PHOTO_BYTES:
                    return self._error(400, f"{i}번째 사진이 너무 큽니다 (6MB 까지)")
                try:
                    from PIL import Image
                except ImportError:
                    return self._error(
                        500, "서버에 Pillow 가 없어 사진을 처리하지 못합니다. "
                             "pip install Pillow 로 설치한 뒤 서버를 다시 켜 주세요.")
                try:
                    im = Image.open(io.BytesIO(raw))
                    im.load()
                    if im.width > 1400:
                        h = round(im.height * 1400 / im.width)
                        im = im.resize((1400, h), Image.LANCZOS)
                    buf = io.BytesIO()
                    im.convert("RGB").save(buf, "PNG")
                    photos.append(buf.getvalue())
                except Exception:                               # noqa: BLE001
                    return self._error(
                        400, f"{i}번째 사진을 열지 못했습니다. 아이폰 사진(HEIC)이면 "
                             "JPG 나 PNG 로 바꿔서 올려 주세요.")

            known = any(str(form.get(k) or "").strip() for k in ("name", "character")) \
                or any(str(v or "").strip() for v in (form.get("fields") or {}).values()) \
                or bool(photos)
            if not known:
                return self._error(400, "캐릭터를 알 수 있는 것이 하나는 필요합니다 — "
                                        "이름 · 설명 · 항목 · 사진 중 아무거나요.")

            job = nh_runner.create(form, photos)
            return self._json({"id": job.id})

        m = re.fullmatch(r"/api/nh/jobs/([\w.-]+)/pick", url.path)
        if m:
            job = nh_runner.get(m.group(1))
            if not job:
                return self._error(404, "그런 작업이 없습니다")
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._error(400, "입력을 읽지 못했습니다")
            try:
                n = int(body.get("n"))
            except (TypeError, ValueError):
                return self._error(400, "n(방향 번호)이 필요합니다")
            try:
                nh_runner.pick(job.id, n)
            except ValueError as exc:
                return self._error(409, str(exc))
            return self._json({"ok": True})

        m = re.fullmatch(r"/api/nh/jobs/([\w.-]+)/board-decision", url.path)
        if m:
            job = nh_runner.get(m.group(1))
            if not job:
                return self._error(404, "그런 작업이 없습니다")
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._error(400, "입력을 읽지 못했습니다")
            decision = str(body.get("decision") or "")
            if decision not in ("approve", "retry"):
                return self._error(400, "decision 은 approve 또는 retry 여야 합니다")
            try:
                if decision == "approve":
                    nh_runner.approve_board(job.id)
                else:
                    nh_runner.retry_board(job.id, note=str(body.get("note") or ""))
            except ValueError as exc:
                return self._error(409, str(exc))
            return self._json({"ok": True})

        m = re.fullmatch(r"/api/nh/jobs/([\w.-]+)/sheet-decision", url.path)
        if m:
            job = nh_runner.get(m.group(1))
            if not job:
                return self._error(404, "그런 작업이 없습니다")
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._error(400, "입력을 읽지 못했습니다")
            decision = str(body.get("decision") or "")
            if decision not in ("approve", "retry"):
                return self._error(400, "decision 은 approve 또는 retry 여야 합니다")
            try:
                if decision == "approve":
                    nh_runner.approve_sheet(job.id)
                else:
                    nh_runner.retry_sheet(job.id, note=str(body.get("note") or ""))
            except ValueError as exc:
                return self._error(409, str(exc))
            return self._json({"ok": True})

        m = re.fullmatch(r"/api/nh/jobs/([\w.-]+)/cancel", url.path)
        if m:
            job = nh_runner.get(m.group(1))
            if not job:
                return self._error(404, "그런 작업이 없습니다")
            job.cancel()
            return self._json({"ok": True})

        # 편집실 — 얹은 것을 작품 폴더(new_harness/runs/<id>/overlay.json)에 저장.
        m = re.fullmatch(r"/api/nh/runs/([\w.-]+)/overlay", url.path)
        if m:
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._error(400, "입력을 읽지 못했습니다")
            try:
                return self._json(nh.write_overlay(m.group(1), body))
            except ValueError as exc:
                return self._error(400, str(exc))

        # 얹은 것을 그림에 굽는다. body 에 얹은 것이 실려 오면 먼저 저장한다.
        m = re.fullmatch(r"/api/nh/runs/([\w.-]+)/bake", url.path)
        if m:
            try:
                body = self._body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                body = {}
            try:
                res = nh.bake_run(m.group(1), body)
            except ValueError as exc:
                return self._error(400, str(exc))
            except overlay.OverlayError as exc:
                return self._error(400, str(exc))
            res["url"] = f"/api/nh/runs/{m.group(1)}/episode.png"
            return self._json(res)

        # 다시 그리기 — 페이지 하나만. 편집실이 아니라 결과 화면(페이지 목록)
        # 에서 부른다. 도는 동안은 /api/nh/regens/<id> 로 진행을 본다.
        m = re.fullmatch(r"/api/nh/runs/([\w.-]+)/page/(\d+)/regen", url.path)
        if m:
            try:
                regen_id = nh_runner.regen(m.group(1), int(m.group(2)))
            except ValueError as exc:
                return self._error(400, str(exc))
            return self._json({"id": regen_id})

        return self._error(404, "없는 주소입니다")


def main() -> int:
    ap = argparse.ArgumentParser(description="웹툰 생성 랜딩페이지 서버")
    ap.add_argument("--port", type=int, default=8800)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--open", action="store_true", help="브라우저를 함께 엽니다")
    args = ap.parse_args()

    pipeline.JOBS_DIR.mkdir(parents=True, exist_ok=True)
    for name, path in (("story-harness", pipeline.STORY),
                       ("webtoon-harness", pipeline.WEBTOON)):
        if not path.exists():
            print(f"[중단] {name} 을 찾지 못했습니다: {path}")
            return 1

    restored = runner.restore()
    if restored:
        print(f"지난 작업 {restored}건을 다시 읽었습니다 (결과 화면은 그대로 열립니다).")

    url = f"http://{args.host}:{args.port}/"
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"랜딩페이지:  {url}")
    print(f"결과물 바로:  {url}result      (이미 만들어 둔 마지막 1화)")
    print(f"내 웹툰 목록: {url}works       (만든 것 전부 · 회차 골라 보기)")
    print(f"편집실(목업): {url}editor      (아무것도 안 돌려도 열립니다)")
    print(f"  그림 조건 {pipeline.CONDITION} · 한 장에 {pipeline.CUTS_PER_SHEET}컷 · "
          f"말풍선과 대사는 그림 안에")
    print("  Ctrl+C 로 종료\n")
    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
