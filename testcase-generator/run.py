#!/usr/bin/env python3
"""테스트 케이스 자동 생성 도구 — 실행 진입점.

사용법
  python run.py                 # http://127.0.0.1:8080
  python run.py --port 9090     # 포트 변경
  python run.py --no-browser    # 브라우저 자동 실행 안 함
설정 파일 config.json 의 port / host 값도 사용할 수 있다 (명령행 인자가 우선).
"""
import argparse
import json
import logging
import os
import sys
import threading
import webbrowser

if sys.version_info < (3, 8):
    sys.exit("Python 3.8 이상이 필요합니다.")

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from tcgen.server import serve  # noqa: E402


def load_config():
    cfg = {"host": "127.0.0.1", "port": 8080, "dataDir": "data", "openBrowser": True}
    path = os.path.join(BASE, "config.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                cfg.update(json.load(f))
        except (OSError, ValueError) as e:
            print(f"[경고] config.json 을 읽지 못했습니다: {e} — 기본 설정으로 실행합니다.")
    return cfg


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser(description="테스트 케이스 자동 생성 도구")
    ap.add_argument("--host", default=os.environ.get("TCGEN_HOST", cfg["host"]))
    ap.add_argument("--port", type=int, default=int(os.environ.get("TCGEN_PORT", cfg["port"])))
    ap.add_argument("--data", default=cfg["dataDir"], help="데이터 저장 폴더")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    data_dir = args.data if os.path.isabs(args.data) else os.path.join(BASE, args.data)
    os.makedirs(os.path.join(data_dir, "logs"), exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(os.path.join(data_dir, "logs", "app.log"), encoding="utf-8")])

    try:
        httpd = serve(args.host, args.port, data_dir, os.path.join(BASE, "static"),
                      os.path.join(BASE, "samples"))
    except OSError as e:
        sys.exit(f"[오류] {args.host}:{args.port} 에서 서버를 시작할 수 없습니다 ({e}).\n"
                 f"       다른 포트로 실행해 보세요: python run.py --port 9090")
    url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}"
    print("=" * 60)
    print(" 테스트 케이스 자동 생성 도구 (Test Case Generator) v1.0")
    print(f" 접속 주소 : {url}")
    print(f" 데이터    : {data_dir}")
    print(" 종료      : Ctrl + C")
    print("=" * 60)
    if cfg.get("openBrowser", True) and not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
