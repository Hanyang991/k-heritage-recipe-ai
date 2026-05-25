# K-Heritage Recipe AI — TODO

기술 명세서 (`k-heritage-recipe-ai-tech-spec-v1_4.docx`) 기준 구현 현황과 백로그.
체크박스는 머지된 코드 기준입니다. 새 항목을 추가하실 때는 `[ ]` 로 두시면 됩니다.

---

## 1. 백엔드 (`apps/api/` — FastAPI)

### 1.1 인증 & 사용자 (Spec §6, §8.2)
- [x] 회원가입 / 로그인 / refresh / me 엔드포인트
- [x] JWT access + refresh 토큰
- [x] bcrypt cost-12 패스워드 해싱
- [x] `UserRole` (user / admin)
- [ ] 이메일 인증 (가입 후 verification token, §6.2)
- [ ] 2FA TOTP (§6.2)
- [ ] 패스워드 재설정 플로우 (forgot-password / reset-password)
- [ ] 소셜 로그인 (Google / Kakao) — Spec 옵션
- [ ] 계정 삭제 API (GDPR / 개인정보보호법, §13)
- [x] 사용자 프로필 편집 (display_name, persona, preferred_regions, preferred_keywords) — `PATCH /v1/private/users/me`

### 1.2 트렌드 (§5, §8.2.2)
- [x] 지역별 인기 키워드 조회
- [x] 시드 데이터 (지역 × 키워드)
- [x] **블렌디드 스코어 ranking** (PR #11) — `0.4 * 현재 ratio + 0.6 * 전주 대비 상승률`
- [x] **네이버 데이터랩 검색어 트렌드 실연동** (`TRENDS_PROVIDER=live`, `NAVER_DATALAB_CLIENT_ID/SECRET`)
- [x] **네이버 데이터랩 쇼핑인사이트 디스커버리** (PR #12, source A — `TRENDS_DISCOVERY_SOURCE=shopping_insight`)
- [x] **Open-domain 디스커버리 — 4 소스 multi-source 파이프라인** (`TRENDS_DISCOVERY_SOURCE=open`)
  - [x] Google Trends RSS (PR #13, source B — `TRENDS_OPEN_GOOGLE_ENABLED`)
  - [x] Naver Search News compound-noun 추출 (PR #14, source C — `TRENDS_OPEN_NAVER_NEWS_ENABLED`)
  - [x] Gemini LLM 한식 변형 제안 (PR #15, source D — `TRENDS_OPEN_LLM_ENABLED`, `GEMINI_API_KEY`)
  - [x] Denylist-only 음식 필터 (PR #13 — novelty 키워드 보존, 정치/스포츠/연예/IT/부동산만 거부)
  - [x] 동시 가져오기 + per-provider 에러 isolation
- [x] **어드민 디버그 엔드포인트** (PR #16 — `GET /v1/admin/trends/debug`)
  - per-provider 통계 (count, sample, elapsed_ms, error text)
  - 키워드별 all-sources attribution
- [x] **Naver DataLab per-chunk 회복력** — 1개 chunk 타임아웃이 전체 refresh를 죽이지 않음 (auth/quota는 그대로 abort)
- [x] **트렌드 시계열 그래프** (PR #23) — 공용 미니 `Sparkline` (SVG, recharts X) + `useTrendSparklines` 훅: 대시보드 트렌드 카드 안에 4주 스파크라인 (상승 녹색 / 하락 적색) — 이미 구현된 클릭-확대 dialog (`TrendSeriesDialog`)와 결합. `/admin/trends/debug` 랭킹 테이블에 `4주 추이` 컬럼 추가되어 PR #22의 "스파크라인 다음 PR 후보" 이월항 닫음. fan-out 최대 30 키워드로 측정해 live datalab 쿠오타 보호.
- [x] **사용자별 즐겨찾는 키워드** (PR #24) — 새 테이블 `user_favorite_keywords (id, user_id, keyword, created_at)` + unique(user_id, keyword), `GET / POST / DELETE /v1/private/me/favorite-keywords` (POST는 멱등, DELETE는 404 없으면). 대시보드 트렌드 카드에 별 토글, 상단에 "내 즐겨찾기 키워드" 섹션 (칩에서 클릭해서 시계열 dialog 열기 또는 X로 해제). optimistic 업데이트 + 실패시 롤백. 알림 그 자체는 PR C로 분리.
- [x] **in-app 알림** (PR #25) — 새 테이블 `notifications (id, user_id, type, payload JSON, created_at, read_at)`. 백그라운드 디텍터 `detect_favorite_keyword_notifications` 가 `refresh_trends` 끝에서 실행되어 (1) 즐겨찾기 키워드가 이번 주 top-N 신규 진입 / (2) `change_percent >= 20%` / (3) 5계단 이상 rank jump 셋 중 하나면 알림 row 생성. `(user, keyword, week_of)` 단위 멱등. 엔드포인트: `GET /v1/private/me/notifications?unread_only=` (items + unread_count 반환), `POST .../{id}/read`, `POST .../read-all`. 사이드바 user row 에 Bell 아이콘 + unread 배지 + Popover 드롭다운 (sonner 와 별개 — 토스트가 아니라 영구 알림 센터). 알림 detector 가 실패해도 trend snapshot 은 보존 (try/except wrap). push/email 채널은 별도 후속 PR (현재 in-app only).
- [x] **운영 전환 인프라** (PR #19) — `.env.example`에 trend 파이프라인 섹션 추가, `docker-compose.yml`에 `trends_refresher` 사이드카 서비스 (`python -m app.jobs.refresh_scheduler`), `TRENDS_REFRESH_HOUR_UTC` 기본 18 UTC (= 03:00 KST). 실제로 `open + live` 로 켜는 건 `apps/api/.env` 의 env 값 변경 (코드 default는 안전한 `curated + mock` 그대로). README "Production rollout" 섹션 참고.
- [x] **Naver News 토큰 노이즈 정리** (PR #18) — min-article-count cutoff (df ≥ 2 기본) + 한국어 stopword set (있다/오늘의/디저트/브랜드/트렌드 등 80+ 패턴). 라이브 결과: `{오늘의, 현지, 브랜드, 트렌드, 신메뉴, 음료, 카페}` → `{밀크티, 다이닝, 아이스크림, 과일, 말차, 베이커리}` 로 정리됨
- [x] **Google Trends 비음식 토큰 cleanup** (PR #20) — `food_filter` denylist에 finance (가계부채/GDP/실업률/예산안/경제성장률), KBO/K-league (`FC` lookaround + 베어스/타이거즈/랜더스/트윈스 등 닉네임), 정치 입법 (법안/탄핵/청문회), 법조 (검찰/판결/체포영장/소송), 군사 (전쟁/미사일/드론), 영화제/시사회 카테고리 추가. `re.IGNORECASE` 활성화 (`mlb`/`fc`/`gdp` 소문자도 매칭). `신곡(?!동)` 좁힘 (신곡동 맛집 보존). 라이브 RSS에서 `가계부채` / `용인 fc 대 충남 아산 fc` / `mlb` reject 확인.
- [x] **bare 인명 사전** (PR #26) — `food_filter.py` 에 `_BARE_PERSON_NAME_DENYLIST` 추가. 영화감독 (홍상수/박찬욱/봉준호/이창동/김지운…), K-pop solo (지드래곤/박효신/임영웅…), 정치인 (이재명/한동훈/윤석열…), 야구 선수 (박찬호/류현진/오타니), 축구 선수 (손흥민/이강인/김민재…), 감독 (김상식/김대호/정해영/허정무/클린스만…), MC (유재석/강호동…), 외국 인명 transliteration (짜라위/트럼프/푸틴/시진핑…) ~60개. **3+ 음절만** 포함 — 2-음절 (`푸틴`/`도티` 등) 은 한식 어휘와 collision 위험 (`푸딩`/`푸성귀`) 때문에 제외. 한국 성씨 한 글자 (`김`/`이`/`박`) 도 제외 (`김치` / `이밥` / `박하사탕` over-reject). PR #20 docstring 의 "Korean person-name leak — passes through" 한계 닫음. 51개 신규 테스트: bare-name reject + surname-syllable food anti-collision (홍어/박하/이밥/조청/정과/김치찌개 등 통과 확인). 추가 leak 발견 시 list 에 append (downstream blended scorer + Gemini 가 1차 safety net 이므로 belt-and-suspenders).
- [x] **broader macro/brand 노이즈** (PR #27) — `food_filter` 에 정부 지출 / 세제 / 무역 (`교부금|지방교부금|특별교부금`, `지원금|보조금|장려금|재난지원금`, `무역수지|경상수지|수출액|수입액|관세인상|관세협상|관세부과`, `부가가치세|법인세|소득세|재산세|종부세|상속세|증여세`, `외환보유고|외환위기|외환시장`), 외국 자동차 브랜드 + 모델 (`테슬라|토요타|혼다|닛산|폭스바겐|벤츠|BMW|아우디|포르쉐|페라리|볼보|렉서스|사이버트럭|모델Y|모델S|모델3|모델X`), 암호화폐 / 가상자산 (`비트코인|이더리움|도지코인|리플|솔라나|알트코인|스테이블코인|가상자산|가상화폐|암호화폐|디지털자산|NFT|업비트|빗썸|코인베이스|바이낸스|크라켄`), SNS / 글로벌 IT (`트위터|메타플랫폼|페이스북|텔레그램|왓츠앱` — 인스타/틱톡/유튜브는 식품 컨텍스트 있어서 의도적 제외), 항공우주 (`누리호|다누리|스페이스X|SpaceX|로켓발사|위성발사|우주왕복선|우주정거장` — 단독 `로켓` 은 `로켓샐러드` 충돌로 제외). 100 신규 테스트 (77 reject + 23 anti-collision: 로켓샐러드/애플파이/김치 수출/발사대 빵집/인스타 핫플 등 모두 통과 확인).
- [x] **어드민 React 페이지** (PR #22) — `/admin/trends/debug` 시각화: 기준일 picker + limit selector, `discovery_type / unique_candidates / scored` 메타 stat 카드, 소스별 카드 (`name / candidate_count / elapsed_ms / error / sample chips`), 병합 랭킹 테이블 (키워드 · `all_sources` 칩 · score · current_ratio · rise%), `POST /v1/admin/trends/refresh` 즉시 갱신 버튼 포함. 사이드바 "트렌드 디버그" 항목 신규. 스파크라인/source venn은 다음 PR 후보로 이월.

### 1.3 고문헌 (§5, §7, §8.2.3)
- [x] 키워드 + 기관 필터 검색 (`GET /v1/documents`)
- [x] 시드 문서 (장서각 / 국립민속박물관 / 문화데이터광장 샘플)
- [x] **장서각 API 실연동** (PR #33) — `HERITAGE_PROVIDER=live` 로 `LiveHeritageAdapter` 활성화. `GET https://jsg.aks.ac.kr/api/search` 라이브 호출 (open API — 키 불필요. spec PDF §3.2 의 API Key 헤더 / `/api/v1/documents/search` 경로는 https://jsg.aks.ac.kr/api/help 와 다른 것을 확인). 한국어 응답 필드 (`자료명`/`유형분류`/`작성시기`/`청구기호`) 를 `HeritageDoc` 으로 정규화, `작성시기` 에서 `year` + `period` (조선전기/조선후기/근대) 자동 derive. `JangseogakAPIError` (404/429/timeout/connect/non-JSON) 시 `MockHeritageAdapter` 로 graceful fallback — empty result 는 정상 정보로 보존. 41 신규 테스트 (28 client + 13 adapter+factory).

#### 1.3.1 추가 고문헌/역사 Open API 소스 (spec §3.1 확장)

Spec PDF §3.1 은 장서각 + 국립민속박물관 + 문화데이터광장 3개 기관만 명시하지만, 실제 한국 고문헌·역사·전통문화 영역에는 더 폭넓고 품질 좋은 공개 데이터셋이 있어 활용 가능한 소스를 확장한다. 아래 4개 소스가 위의 NFM / 문화데이터광장보다 우선순위가 높음.

- [x] **한국학자료포털 (한국학중앙연구원) Open API** — `HERITAGE_PROVIDER=live` + `HERITAGE_LIVE_SOURCE=koreanstudies` 로 `LiveKoreanstudiesAdapter` 활성화. `GET http://kostma.aks.ac.kr/OpenAPI/request.aspx` 라이브 호출 (open API — 키 불필요, 장서각과 동일). 응답이 JSON 이 아닌 **XML** 이라 `<ksm>/<items>/<item>` 구조 + `<기본정보>/<분류>/<작성지역>/<작성시기>` 한국어 태그를 `KoreanstudiesSearchResult` → `HeritageDoc` 으로 정규화. `작성지역 @현재주소` 가 있어 장서각 대비 region 데이터가 풍부함 (장서각은 region 정보를 search response 에 노출 안 함). period bucket (조선전기 ≤ 1592 / 조선후기 1593–1896 / 근대 ≥ 1897) 은 장서각과 동일 — 추후 multi-source fan-in 시 score 비교 가능. detail=1 (기본정보) 이 기본값, detail=2 (안내정보) 로 표제어/문단 summary 확장 가능. `KoreanstudiesAPIError` (404/429/timeout/connect/non-XML/unexpected-root) 시 `MockHeritageAdapter` 로 graceful fallback (장서각 패턴 그대로). 53 신규 테스트 (26 client/parser + 23 adapter + 4 factory routing). 운영기관: 한국학중앙연구원 (장서각과 동일 기관). 제공 데이터: 전국 권역 수집 고문헌·고문서 문헌정보, 고지도, **디지털 고문헌 용례사전**.
- [x] **국립중앙도서관 (NLK) Open API** — `HERITAGE_PROVIDER=live` + `HERITAGE_LIVE_SOURCE=nlk` + `NLK_API_KEY=<발급키>` 으로 `LiveNlkAdapter` 활성화. `GET https://www.nl.go.kr/NL/search/openApi/search.do` (장서각/한국학자료포털과 달리 **인증키 필수** — 신청 위치 https://www.nl.go.kr/NL/contents/N31101030500.do, admin approval 필요). XML 응답 (`<channel>/<list>/<item>`) 을 `NlkSearchResult` → `HeritageDoc` 으로 정규화 — `control_no` 는 KORCIS-stable identifier 라 후속 multi-source fan-in 의 dedupe anchor 로 사용 예정. `category=고문헌` 가 기본값 (heritage adapter 이므로). `pub_year_info` 가 `"2012"` / `"201201"` / `"순조 14년(1814년)"` 3가지 shape 을 모두 지원 (장서각/한국학자료포털과 동일한 4-digit regex + period bucket). NLK 가 search response 에 region 을 노출하지 않아 region 필터는 no-op (KDC 분류명 + 청구기호는 summary 에 fold-in). `NlkAPIError` 는 upstream `<error_code>` (010 NO KEY / 011 INVALID KEY / 012 DATA LIMIT 500 / 013 CATEGORY / 014 PARAMETER) 를 `.error_code` 로 노출해 로그에서 auth 문제와 transient 장애를 구별 가능. **키 없을 때**: 팩토리가 `MockHeritageAdapter` 로 자동 degrade (`HERITAGE_LIVE_SOURCE=nlk` 여도 boot 실패 안 함) — 키 도착 후 `.env` 만 업데이트하면 즉시 라이브. 운영기관: 국립중앙도서관 (NLK). 제공 데이터: 국가자료종합목록 (KOLIS-NET), **한국고문헌종합목록 (KORCIS)** — 가장 광범위한 표준 서지 데이터.
- [ ] **국사편찬위원회 Open API (공공데이터포털 경유)** — **deferred (조사 결과 공식 OpenAPI 부재 확인)**
  - 운영기관: 국사편찬위원회
  - 조사 결과: data.go.kr 등록 데이터셋은 "역사지리정보 배경지도" 1개뿐 (이미지/지도 API, metadata 아님). `db.history.go.kr` / `sillok.history.go.kr` 는 검색 UI 만 노출 (HTML 응답, JSON/XML public endpoint 없음). `people.history.go.kr` / `api.history.go.kr` 는 미존재. 따라서 다른 3개 소스와 같은 contract-bound OpenAPI 가 부재함.
  - 향후 옵션 (별도 PR 후보): (1) `sillok.history.go.kr` HTML 스크레이퍼 — 조선왕조실록 음식·의례·진찬 자료, fragile contract; (2) NIHC 간행자료 다운로드 페이지를 seed 확장으로 활용 — 어댑터 아님; (3) 공공데이터포털 신규 API 등록 시 재평가.
  - 어댑터 위치 예정 (확정 시): `app/services/heritage/nihc.py`
- [x] **기호유학 고문헌 통합정보시스템 (충남대) Open API** — `HERITAGE_PROVIDER=live` + `HERITAGE_LIVE_SOURCE=gihohak` 으로 `LiveGihohakAdapter` 활성화. `GET http://giho.cnu.ac.kr/api/literature/search.do` (open API — 키 불필요, 장서각/한국학자료포털과 동일). XML 응답 (`<gihoConfucianism>/<searchResult>/<literature>`) 을 `GihohakSearchResult` → `HeritageDoc` 으로 정규화. `type` 파라미터로 `OB` (고서, 육서심원 포함) / `OD` (고문서, 금석문 포함) 선택 — heritage 어댑터 이므로 기본값 `OB` (고서가 음식·의례 grounding 에 더 적합). `target` 파라미터로 `all/title/creator/abstract` 4-way 교차 검색 (기본 `all`). `<created>` 가 `"미상"` 또는 정수 연도 2가지 shape 을 모두 지원 (장서각/한국학자료포털/NLK 와 동일한 4-digit regex + 1593/1897 boundary). 기호유학은 curation scope 가 **충청권 가문/서원** 으로 균일하므로 모든 record 에 `region="충청"` 정적 라벨 부착 — 후속 multi-source fan-in 에서 `region=충청` 쿼리가 기호유학 으로 라우팅됨. `classFullNm` (예: `잡저류>음식류`) 의 `>`-separated hierarchy 를 category 로 사용. `GihohakAPIError` (404/429/timeout/connect/non-XML/unexpected-root) 시 `MockHeritageAdapter` 로 graceful fallback. 신규 테스트 (client/parser + adapter + factory routing). 운영기관: 충남대학교 (국가DB사업). 제공 데이터: 기호유학권 (충청도 + 한강 유역) 고서/고문서/금석문 + 인물 네트워크 — 장서각(왕실)/한국학자료포털(권역별)/NLK(전국) 가 갖지 못한 지역·학파 특화 layer 추가.

공통 설계 원칙 (장서각 어댑터 패턴 답습):
- 각 소스마다 thin `*SearchClient` (httpx) + `*Adapter (HeritageAdapter)` + 응답 정규화로 `HeritageDoc` 생성
- `MultiSourceHeritageAdapter` (예정) 에서 fan-in 후 dedupe(by external_id) + recency / 인지도 기반 가중치 정렬
- 단일 소스 실패는 isolation (장서각이 mock fallback 가지듯, 각 소스별 try/except → 해당 소스만 결과 skip, 나머지 정상 응답 유지)
- `quarantine_logs` 테이블에 스키마 변경된 raw payload 저장 (spec §3.4)
- KOGL 1유형 출처 표시 자동화 (`source_attribution` 필드)
- 각 소스별 namespace 분리 (Vertex AI Vector Search 인덱싱 대비)

- [ ] ~~**국립민속박물관 API 실연동** (`NFM_API_KEY`)~~ — 우선순위 낮춤 (위 4개 신규 소스로 대체)
- [ ] ~~**문화데이터광장 API 실연동** (`CULTURE_API_KEY`)~~ — 우선순위 낮춤 (위 4개 신규 소스로 대체)
- [ ] **Vertex AI Vector Search** 임베딩 + 인덱싱 파이프라인 (소스별 namespace = jangseogak / koreanstudies / nlk / nihc / giho)
- [ ] 문서 상세 페이지 API (원문, 번역, 메타데이터)
- [ ] 라이선스 / 저작권 표기 강화 (§13)

### 1.4 레시피 (§5, §8.2.4)
- [x] 생성 (3 후보, mock LLM, 결정론적 시드)
- [x] 목록 / 상세 / 삭제
- [x] PDF 다운로드 (`reportlab`, 무료=워터마크 / Pro=plain)
- [x] 고증 인증서 (Pro+ 한정, 402 on free)
- [x] DB 저장 + 상태(draft / pending_review / approved / rejected / flagged)
- [x] `source_attribution` 자동 첨부
- [x] 별점 / 판매중 토글 저장 (PATCH `/v1/private/recipes/{id}` + 프론트 위젯)
- [ ] **실 Gemini 2.5 Pro API 연동** (`LLM_PROVIDER=live`, `GEMINI_API_KEY`)
- [ ] 관련 레시피 추천 (벡터 유사도 또는 태그 기반)
- [ ] 재료 / 단계 사용자 편집
- [ ] 비용 분석 더 세분화 (재료비 / 소모품 / 인건비)
- [ ] 식약처 식품안전 키워드 필터 (금지 재료, §13)
- [ ] 알러지 / 식이제한 검증 (재료 vs `diet` 옵션 매칭)

### 1.5 구독 & 결제 (§5, §8.2.5, §12)
- [x] Free / Pro / B2B 3-tier 모델
- [x] Free 플랜 월 3건 쿼터 + 429 응답
- [x] 플랜 변경 mock 엔드포인트
- [x] TossPayments 빌링키 mock 어댑터
- [ ] **TossPayments 실연동** (`PAYMENTS_PROVIDER=live`, `TOSS_SECRET_KEY`)
- [ ] 빌링키 발급 콜백 (clientKey + customerKey 흐름)
- [ ] 정기결제 잡 (cron / Celery / Cloud Scheduler)
- [ ] 결제 실패 retry 로직 (`retry_count`, exponential backoff)
- [ ] 환불 / 구독 취소 API
- [ ] 영수증 / 세금계산서 발행 (B2B)
- [ ] 사용량 미터링 + 청구 (B2B per-seat / per-API-call)

### 1.6 관리자 (§5, §8.2.6, FR-07)
- [x] 검수 큐 (pending / approved / rejected / flagged 필터)
- [x] 상태 변경 API
- [x] 거부 사유 입력 (반려 시 필수) + 사용자 상세 화면에 노출
- [ ] 일괄 승인 / 거부
- [ ] 통계 대시보드 (일별 생성량, 승인율, 인기 키워드)
- [ ] 사용자 관리 (BAN / 강등)
- [ ] 감사 로그 (admin action 추적, §13)

### 1.7 인프라 / 운영
- [x] SQLAlchemy 2.x + Alembic migrations
- [x] SQLite(dev/test) / Postgres(compose)
- [x] 어댑터 패턴 (LLM / Heritage / Payments)
- [x] 372개 pytest 통과 (auth / recipes / admin / trends 4-source / quotas / PDF + refresh / 온보딩 / food_filter denylist 회귀 포함)
- [x] ruff lint + format check
- [ ] **Redis 캐싱** (현재 compose에만 떠있고 코드에서 미사용) — 트렌드 / 문서 검색 캐시
- [ ] 백그라운드 잡 큐 (Celery / RQ / Cloud Tasks)
- [ ] 구조화 로깅 (JSON, request_id correlation)
- [ ] OpenTelemetry 트레이싱
- [ ] Sentry / 에러 트래킹
- [ ] Rate limit 미들웨어 (`free_plan_hourly_rate_limit` 설정값만 있고 미적용)
- [ ] 헬스체크 / readiness 엔드포인트
- [ ] DB 마이그레이션 자동 적용 (현재 시드만)

---

## 2. 프론트엔드 (`apps/web/` — React + Vite + Tailwind v4 + shadcn)

### 2.1 페이지
- [x] `/login` — 로그인 / 회원가입 + 데모 계정 안내
- [x] `/dashboard` — 트렌드 카드 + 최근 레시피
- [x] `/generate` step1 — 키워드 / 지역 / 식이 / 메뉴 타입 선택
- [x] `/generate/step2` — 고문헌 매칭 + 선택
- [x] `/generate/result` — 3개 후보 + 추천 표시
- [x] `/recipes` — 내 레시피 목록 + 삭제
- [x] `/recipes/:id` — 상세 + PDF / 인증서 다운로드 + SNS 문구 복사
- [x] `/documents` — 키워드 + 기관 검색
- [x] `/subscription` — 3개 플랜 카드 + 현재 플랜
- [x] `/admin` — 검수 큐 (관리자 전용)
- [x] `/admin/trends/debug` — 트렌드 파이프라인 소스별 통계 + 병합 랭킹 시각화 (관리자 전용, PR #22)
- [x] **`/onboarding`** — 가입 직후 사용자 페르소나 / 선호 지역 / 키워드 설정 (§8.2.1)
- [ ] `/profile` — 사용자 정보 / 비밀번호 변경
- [ ] `/recipes/:id/edit` — 레시피 직접 편집
- [ ] `/documents/:id` — 고문헌 상세
- [ ] `/billing/history` — 결제 내역

### 2.2 인증 & 라우팅
- [x] `AuthContext` + `useAuth()`
- [x] `ProtectedRoute` (auth + admin 가드)
- [x] JWT localStorage 저장 (`kh.access_token`, `kh.refresh_token`)
- [x] 사이드바 인증 / 역할별 메뉴
- [x] Refresh token 자동 갱신 (api 클라이언트가 401 수신 시 1회 refresh 후 동일 요청 재시도)
- [ ] 비로그인 사용자 랜딩 페이지

### 2.3 API 클라이언트 (`src/lib/api.ts`)
- [x] 타입드 endpoint wrapper 전부
- [x] 자동 Authorization 헤더 주입
- [x] 401 / 402 / 429 핸들링
- [ ] React Query 도입 (현재 useEffect + setState 패턴) — 캐싱 / 리페치 / optimistic update
- [ ] 글로벌 에러 토스트 인터셉터

### 2.4 UI / UX
- [x] shadcn/ui 컴포넌트 라이브러리
- [x] Tailwind v4 + 디자인 토큰
- [x] 한글 폰트 (Pretendard / Noto Sans KR)
- [ ] 다크 모드 토글 (`next-themes` 이미 설치됨)
- [ ] 반응형 모바일 대응
- [ ] i18n (ko / en 동시 지원)
- [ ] 로딩 스켈레톤 통일
- [ ] 에러 바운더리

---

## 3. 인프라 / DevOps

- [x] `docker-compose.yml` (postgres + redis + api + web)
- [x] API / Web Dockerfile
- [x] GitHub Actions CI (ruff / pytest / tsc / vite build)
- [x] Devin 환경 blueprint
- [x] `.gitignore`, `README.md`, `tsconfig.json`
- [ ] **GCP Cloud Run 배포** (api + web)
- [ ] **Cloud SQL Postgres** 프로비저닝
- [ ] **Vertex AI Vector Search** 인덱스
- [ ] **Cloud Storage** (PDF / 이미지 캐시)
- [ ] **Cloud Scheduler** (트렌드 수집, 정기결제)
- [ ] Terraform / Pulumi IaC
- [ ] 스테이징 / 프로덕션 환경 분리
- [ ] CI에서 docker-compose smoke test
- [ ] 시크릿 관리 (Secret Manager / Doppler)
- [ ] 도메인 / TLS / CDN

---

## 4. 테스트

- [x] 백엔드 단위 / 통합 테스트 372개 (auth / recipes / admin / trends 4-source / quotas / PDF + refresh / food_filter denylist 회귀)
- [ ] **프론트엔드 단위 테스트** (Vitest + React Testing Library)
- [ ] **E2E 테스트** (Playwright) — 핵심 사용자 플로우
  - [ ] 회원가입 → 로그인 → 레시피 생성 → PDF 다운로드
  - [ ] 관리자 로그인 → 검수 큐 → 승인
  - [ ] Free 쿼터 초과 → 구독 페이지 리다이렉트
- [ ] 부하 테스트 (k6 / Locust) — 생성 동시성, 쿼터 정합성
- [ ] 보안 점검 (OWASP top 10, JWT 시크릿, SQL 인젝션 회귀)

---

## 5. 컴플라이언스 / 법무 (§13)

- [ ] 개인정보 처리방침 페이지
- [ ] 이용약관 페이지
- [ ] 가입 시 약관 동의 체크박스
- [ ] 쿠키 배너 (KISA / GDPR)
- [ ] 데이터 보관 / 삭제 정책 (DB 마이그레이션 포함)
- [ ] 사업자 정보 / 통신판매업 신고
- [ ] 고문헌 출처 표기 자동화 (현재 텍스트만, 라이선스별 분기 필요)

---

## 6. 보류 (실 키 / 의사결정 대기)

| 항목 | 차단 사유 | 어댑터 준비 |
|---|---|---|
| Gemini 2.5 Pro 호출 | `GEMINI_API_KEY` 필요 | ✅ (`LLMAdapter`, `NotImplementedError`) |
| 장서각 API | API 키 + 발급 절차 | ✅ |
| 국립민속박물관 API | API 키 | ✅ |
| 문화데이터광장 API | API 키 | ✅ |
| TossPayments | `TOSS_SECRET_KEY` + `TOSS_CLIENT_KEY` + 가맹점 등록 | ✅ |
| Vertex AI Vector Search | GCP 프로젝트 + 결제 활성화 | ⏸ (스켈레톤만) |
| 이메일 발송 (SendGrid / Resend) | 도메인 + DKIM 설정 | ❌ (아직 시작 안 함) |

---

## 7. 우선순위 제안

**Now (다음 스프린트)**
1. ~~별점 / 판매중 토글 백엔드 저장~~ ✅ (PR: rating + rejection)
2. ~~관리자 거부 사유 입력 + 사용자 알림~~ ✅ (PR: rating + rejection)
3. ~~Refresh token 자동 갱신~~ ✅ (PR: auto-refresh)
4. ~~온보딩 페이지~~ ✅ (PR: onboarding)

**Next (실 키 받으면)**
1. Gemini 실연동
2. 장서각 / 국립민속박물관 / 문화데이터광장 크롤러
3. TossPayments 정기결제

**Later (스케일링)**
1. Vertex Vector Search
2. Cloud Run 배포
3. 부하 테스트 / 모니터링
4. i18n
