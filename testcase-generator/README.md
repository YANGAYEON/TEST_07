# 테스트 케이스 자동 생성 도구 (Test Case Generator)

요구사항 문서 · WebSquare5 XML · Java · SQL(MyBatis Mapper 포함)을 **규칙 기반**으로 분석해 테스트 케이스 초안을 만들고,
개발자가 검토·수정·결과 입력 후 **Excel 테스트 문서**로 내려받는 로컬 웹 도구입니다.

- **설치 불필요**: Python 3.8+ 표준 라이브러리만 사용 (pip 설치 없음, 외부 라이브러리 반입 불필요)
- **폐쇄망 전용 설계**: 외부 인터넷·외부 AI API·CDN·웹폰트를 전혀 사용하지 않음. 기본 바인딩 `127.0.0.1`
- **원본 보호**: 업로드한 파일은 사본으로만 읽고, 원본 파일·업무 시스템·DB 에 접근하지 않음

---

## 1. 실행 방법

```bash
# Windows: start.bat 더블클릭   /   macOS·Linux: ./start.sh
python run.py                 # http://localhost:8080 (브라우저 자동 실행)
python run.py --port 9090     # 포트 변경
python run.py --no-browser    # 브라우저 자동 실행 안 함
```

- 포트·호스트·데이터 폴더는 `config.json` 으로도 설정할 수 있습니다 (명령행 인자 > 환경변수 `TCGEN_PORT` > config.json).
- 처음이라면 화면의 **「샘플 프로젝트로 체험하기」** 를 누르세요. `samples/` 의 예제 파일로 분석까지 한 번에 실행됩니다.
- 종료: 콘솔에서 `Ctrl + C`. 저장된 프로젝트는 `data/projects/` 에 남아 다시 실행해도 불러올 수 있습니다.

테스트 실행:

```bash
python -m unittest discover -s tests -v
```

## 2. 사용 흐름

| 단계 | 화면 | 내용 |
|---|---|---|
| ① 프로젝트 | 좌측 사이드바 | 화면/업무 단위로 생성 · 검색 · 불러오기 · 삭제. 이름/설명은 상단에서 바로 수정 후 **저장(Ctrl+S)** |
| ② 분석 자료 | `1 분석 자료` 탭 | 요구사항 직접 입력 + 파일 업로드(다중 선택·드래그). 파일별 **포함/제외 스위치**, 내용 미리보기 |
| ③ 분석 실행 | 같은 탭 하단 | 분석 시작 / **취소**, 진행률·단계 표시, 파일별 오류(파일명·라인) 표시. 한 파일 오류가 전체를 멈추지 않음 |
| ④ 검토·편집 | `2 테스트 케이스` 탭 | 통계(진행률·성공/실패/보류/미실행), 검색·필터(상태/분류/중요도/기능/확인 필요), 정렬, 상태 즉시 변경, 일괄 변경·삭제, 행 클릭 → 상세 편집(추가·수정·복사·삭제, 결과 입력) |
| ⑤ 리포트 | `3 분석 리포트` 탭 | 파일별 분석 결과, 분류별 건수, **통합 분석으로 합쳐진 입력 항목과 근거** |
| ⑥ Excel | 상단 버튼 | 전체 / 실패 건만(⋯ 메뉴) / 선택 항목 다운로드 |

## 3. 기술 스택

| 구분 | 선택 | 이유 |
|---|---|---|
| Backend | Python 3.8+ `http.server` (ThreadingHTTPServer) | 설치 없이 실행, 폐쇄망 반입 부담 없음 |
| Frontend | HTML · CSS · Vanilla JavaScript | 빌드 도구/CDN 불필요 |
| 분석 엔진 | XML: `xml.parsers.expat`(라인 번호 보존) · Java/SQL: 정규식 + 괄호 매칭 경량 파서 | 표준 라이브러리만 사용, AST 분석기로 교체 가능하도록 분리 |
| 저장 | 로컬 JSON 파일 (임시 파일 → `os.replace` 원자적 저장) | 프로젝트 단위 백업·이동이 쉬움 |
| Excel 입력/출력 | `zipfile` 로 OOXML(xlsx) 직접 읽기/쓰기 | Apache POI·openpyxl 없이 동작 |

## 4. MVP 범위

**구현 완료 (화면에 보이는 기능은 모두 실제 동작)**

- 프로젝트 생성/저장/불러오기/삭제, 요구사항 직접 입력, 다중 파일 업로드(txt·md·xlsx·xml·sql·java), 파일 포함/제외·미리보기
- 분석 실행/취소/진행률/오류 표시 (백그라운드 작업, 취소 시 프로젝트 변경 없음)
- 분석기: 요구사항(문장 패턴/키워드) · Excel 요구사항 · WebSquare5 XML · SQL · MyBatis Mapper · Java
- 통합 분석: 요구사항·XML·SQL 의 같은 항목 병합, 중복 테스트 제거, 근거 자료 연결, 중요도 자동 보정
- 테스트 케이스 편집(추가/수정/삭제/복사/ID 자동 생성·중복 검사/분류·중요도·상태 변경), 자동 생성 vs 개발자 수정 구분
- 재분석 시 개발자 수정 내용·실행 결과·테스트 ID 보존, 변경된 파일 감지 → 회귀 테스트 생성
- 테스트 결과 관리(상태·실행 일자·수행자·실제 결과·실패 사유·비고), 실패 건 조회, 상태별 건수
- Excel 다운로드(헤더 스타일·열 너비 자동·줄바꿈·행 높이·자동 필터·틀 고정·상태 드롭다운·상태 색상·요약 시트)

**제외 / 향후 과제**

- 구 Excel(.xls) 읽기 — 안내 메시지 후 .xlsx 저장 요청
- Java AST(타입·호출 그래프) 분석, SQL 실제 실행·DB 연결 (분석 모듈과 실행 모듈 분리만 해 둠)
- 로컬 LLM 연동 (아래 6장의 확장 지점 참고)
- 다중 사용자 동시 편집 / 로그인

## 5. 프로젝트 구조와 파일 역할

```
testcase-generator/
├─ run.py                  실행 진입점 (포트/호스트 설정, 로깅, 브라우저 실행)
├─ config.json             기본 설정 (host, port, dataDir, openBrowser)
├─ start.bat / start.sh    더블클릭 실행용
├─ tcgen/
│  ├─ server.py            REST API + 정적 파일 서버, 입력 검증·오류 응답
│  ├─ jobs.py              분석 작업(스레드) 관리: 진행률·취소·파일 단위 오류 격리·병합·저장
│  ├─ storage.py           프로젝트 JSON 저장소, 업로드 파일 사본 관리 (원자적 저장)
│  ├─ excel_writer.py      xlsx 생성 (테스트케이스 시트 + 요약 시트)
│  ├─ analyzers/           ── 분석 모듈 (텍스트 → Fact) ──
│  │  ├─ __init__.py       분석기 레지스트리, 파일 유형 판별(detect_type), analyze_file
│  │  ├─ common.py         Fact/근거 구조, 식별자→한글 라벨(약어 사전), 정규화 키, 조사 처리, 인코딩 판별
│  │  ├─ requirement.py    요구사항 문장 분석 (기능·입력·필수·길이·범위·결과 없음·권한·중복·조건·해석 불가)
│  │  ├─ excel_reader.py   xlsx 요구사항 문서 읽기
│  │  ├─ xmltree.py        라인 번호 보존 XML 트리 (expat)
│  │  ├─ websquare.py      WebSquare5 화면 분석 (input/calendar/select/checkbox/radio/textarea/button/gridView/generator/submission/actionId/스크립트 이벤트)
│  │  ├─ sql_analyzer.py   SQL·MyBatis 분석 (SELECT/INSERT/UPDATE/DELETE, WHERE·BETWEEN·IN·LIKE·IS NULL·비교, JOIN, CASE, NVL, GROUP/ORDER BY, 페이징, <if> 동적 조건, ${} 치환)
│  │  └─ java_analyzer.py  Java 분석 (클래스·메서드·매개변수·반환값, if/else 체인, switch, null/empty 체크, 비교, try-catch, throw, 반복문)
│  └─ generator/           ── 테스트 케이스 생성 모듈 (Fact → 테스트 케이스) ──
│     ├─ engine.py         규칙 엔진: 통합 컨텍스트 구성 + Fact 종류별 규칙
│     ├─ builder.py        키 기반 중복 제거, 근거 병합, 중요도 보정, 문장 조립
│     └─ merge.py          재분석 병합 (개발자 수정 보존, ID 부여)
├─ static/                 index.html · app.css · app.js (UI)
├─ samples/                예제 요구사항·WebSquare XML·Mapper·SQL·Java
├─ tests/                  unittest
└─ data/                   (실행 시 생성) projects/*.json, 업로드 사본, logs/app.log
```

## 6. 처리 구조 (입력 → 처리 → 출력)

```
요구사항/파일 ──► analyzers (규칙 기반)      ──► Fact 목록 ──► generator.engine ──► 초안 테스트 케이스 ──► merge ──► 저장
                 └ 파일별 오류는 해당 파일만 실패     (중간 표현)     └ 같은 key = 같은 테스트,       └ 수정본 보존
                                                                     근거만 합침                   └ 신규 ID 부여
```

- **Fact**: 분석기와 생성기 사이의 계약. 예) `{"kind":"field","label":"시작일","fieldType":"date","required":true,"src":{file,type,line,detail}}`
- **로컬 LLM / 사내 AI 연결 시**: `analyze(text, file_name, is_cancelled) → AnalysisResult(facts)` 를 구현한 분석기를
  `tcgen/analyzers/__init__.py` 의 `ANALYZERS` 에 등록하면 생성·병합·Excel 은 그대로 재사용됩니다.
- **AST 분석 교체**: `java_analyzer.py` / `sql_analyzer.py` 를 같은 Fact 형식으로 대체하면 됩니다.

### 주요 생성 규칙 (요약)

| 대상 | 생성되는 테스트 |
|---|---|
| 입력(text) | 정상 입력, 미입력(필수/선택/미확인), 공백만 입력, 허용 문자 외 입력, 최대 길이·초과, 최소 길이 미만 |
| 날짜 / 기간 | 정상 날짜, 형식 오류, 존재하지 않는 날짜, 시작=종료, 시작>종료, 경계일 포함 여부(BETWEEN), 최대 조회 기간 |
| Selectbox / Radio / Checkbox | 정상 코드, 미선택, 미정의 코드, 기본값 / 옵션별 선택 / 선택·미선택·복수·전체 선택 |
| GridView | 결과 존재, 결과 없음, 1건, 다건, 중복 표시, 행별 버튼, 전체 선택, 행 미선택 후 처리 버튼 |
| Button | 정상 클릭, 필수값 누락 클릭, 중복 클릭, 권한 없음, 확인창 취소 |
| SQL | 결과 있음/없음, 고정 조건, 코드 조건, IN 빈 목록, LIKE 와일드카드, NULL 조건, JOIN 미일치, CASE 분기, NVL, 정렬·집계·페이징, 등록 후 검증·중복 키·NOT NULL, 수정/삭제 0건·WHERE 누락·연관 데이터, `${}` 인젝션 |
| Java | 정상 호출, null/빈 값, 등가 분기별 + 미정의 값, 비교 경계값(충족/미충족), switch case/default, catch 예외, 반복 0건/다건, throws |
| 요구사항 | 기능 정상 수행, 처리 후 데이터 반영, 숫자 경계값, 권한 있음/없음, 중복 처리, 조건 문장, 해석 불가 문장 |

규칙으로 확정할 수 없는 내용은 임의로 확정하지 않고 **「개발자 확인 필요」/「업무 규칙 확인 필요」** 로 표시됩니다(목록의 노란 태그, Excel 노란 셀).
여러 자료(예: 요구사항 + XML + SQL)에서 같은 테스트가 도출되면 하나로 합치고 근거를 모두 연결하며 중요도를 한 단계 올립니다.

## 7. 예외 처리 · 보안

- 파일 미선택 분석, 지원하지 않는 형식, XML 파싱 오류(라인·컬럼), 인코딩 오류(UTF-8/CP949/UTF-16 자동 판별), 대용량(분석 5MB·업로드 20MB 제한),
  Excel 생성 오류, 저장 오류(원자적 저장), 테스트 ID 중복, 분석 중 취소/오류 → 모두 메시지로 안내하고 프로그램은 계속 동작
- 로그(`data/logs/app.log`)에는 파일명·건수 등 메타 정보만 기록하며 업무 데이터·소스코드 본문은 기록하지 않습니다.
- 외부로 나가는 네트워크 요청이 코드 어디에도 없습니다 (`urllib`/`requests` 미사용, 프론트엔드 외부 리소스 없음).
