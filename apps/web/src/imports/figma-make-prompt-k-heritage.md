# K-Heritage Recipe AI — Figma Make 프롬프트

아래 프롬프트를 Figma Make에 그대로 붙여넣어 사용하세요.
화면별로 분리되어 있으니 원하는 화면부터 순서대로 생성하면 됩니다.

---

## ✅ 공통 디자인 시스템 (먼저 생성 — 모든 화면의 기반)

```
Create a design system for a Korean heritage recipe AI SaaS platform called "K-Heritage Recipe AI".

Design language: Premium Korean cultural aesthetic meets modern SaaS. Clean, trustworthy, warm.

Color palette:
- Primary: Deep Indigo #3730A3 (brand, CTAs)
- Primary Light: #6366F1 (hover states)
- Accent: Warm Amber #D97706 (heritage/traditional highlights, badges)
- Accent Light: #FEF3C7 (accent backgrounds)
- Success: #059669
- Error: #DC2626
- Neutral 900: #111827 (headings)
- Neutral 600: #4B5563 (body text)
- Neutral 200: #E5E7EB (borders, dividers)
- Neutral 50: #F9FAFB (page background)
- White: #FFFFFF (cards, panels)

Typography:
- Font: Pretendard (Korean) / Inter (English fallback)
- Display: 32px Bold — page titles
- Heading 1: 24px SemiBold — section titles
- Heading 2: 18px SemiBold — card titles, subsections
- Body: 16px Regular — main content
- Body Small: 14px Regular — labels, metadata
- Caption: 12px Regular — timestamps, footnotes

Grid: 8pt base grid. Desktop 1280px max-width, 24px gutters, 12 columns.

Components to include:
- Primary Button (Indigo fill, white text, 8px radius, 40px height)
- Secondary Button (white fill, Indigo border)
- Ghost Button (no border, Indigo text)
- Badge: "전통 고증" amber, "Pro" indigo, "Free" gray
- Recipe Card (white, 12px radius, subtle shadow, image area top, tag row, title, 3-line description, bottom action row)
- Trend Chip (hashtag style, #EDE9FE background, indigo text)
- Input field (44px height, 6px radius, focus ring indigo)
- Toast notification (success/error/info variants)
- Loading skeleton (pulsing gray bars)
- Modal overlay (backdrop blur, centered card)
- Navigation sidebar (64px wide collapsed / 240px expanded, logo top, icon+label items)
```

---

## 📊 화면 1 — 트렌드 대시보드 (`/dashboard`)

```
Design a dashboard screen for "K-Heritage Recipe AI" using the established design system.

Screen: Trend Dashboard (/dashboard)
Viewport: 1280px desktop, with left sidebar navigation (240px expanded).

Layout sections:

[TOP HEADER BAR]
- Page title "트렌드 대시보드" (Display, Neutral 900)
- Subtitle "이번 주 급상승 키워드를 확인하고 레시피를 생성하세요" (Body Small, Neutral 600)
- Right: Region filter dropdown (전국 / 서울 / 경기 / 전라 / 경상 / 충청 / 강원 / 제주), "레시피 생성하기" Primary Button

[TREND KEYWORDS SECTION]
- Section label "📈 이번 주 TOP 20 트렌드" (Heading 2)
- Grid of 20 Trend Chips in 4 rows × 5 columns
- Each chip shows: rank number (bold), hashtag name in Korean, up/down arrow with % change
- Top 3 chips use Amber accent color. Rank 4–10 use Indigo. Rank 11–20 use Gray.
- Example chips: #1 ↑32% 쑥라떼, #2 ↑28% 오미자에이드, #3 ↑19% 흑임자크림, #4 ↑15% 매실청소다

[RECENT RECIPES SECTION]
- Section label "📋 최근 생성한 레시피" with "전체보기 →" link right-aligned
- Horizontal scroll row of 3 Recipe Cards
- Card 1: "전주 쑥 인절미 라떼" — tag [전라도] [조선후기] — "장서각 고문헌 기반" caption
- Card 2: "제주 오미자 에이드" — tag [제주] [근대] — approved badge
- Card 3: "경주 흑임자 크림 케이크" — tag [경상도] [조선전기] — pending badge

[SIDEBAR NAVIGATION]
- Logo top: "K-Heritage" with small traditional pattern icon
- Nav items with icons: 대시보드 (active, indigo highlight), 레시피 생성, 내 레시피, 고문헌 탐색, 구독 관리
- Bottom: user avatar + name + plan badge (Free/Pro)
```

---

## 🍽️ 화면 2 — 레시피 생성 (`/generate`)

```
Design the recipe generation screen for "K-Heritage Recipe AI".

Screen: Recipe Generation (/generate)
Viewport: 1280px desktop, left sidebar navigation visible.

This is a 3-step wizard. Show Step 2 as the active state (step indicator at top).

[STEP INDICATOR]
- 3 steps horizontal: ① 옵션 선택 → ② 고문헌 매칭 → ③ 결과 확인
- Step 1: completed (indigo filled circle with checkmark)
- Step 2: active (indigo outline circle, bold label)
- Step 3: upcoming (gray circle)

[STEP 2 — 고문헌 매칭 PANEL]
- Card with white background, 16px padding
- Heading: "입력하신 조건에 맞는 고문헌을 찾고 있습니다"
- Show 3 matched document cards in a vertical list:
  - Document Card: [장서각 아이콘] "음식디미방 (1670)" — Region: 경상도 — Era: 조선후기 — Match score bar 94%
  - Document Card: [국립민속박물관 아이콘] "규합총서 (1809)" — Region: 전국 — Era: 조선후기 — Match score bar 87%
  - Document Card: [문화데이터광장 아이콘] "향토음식 DB — 전주 전통음료" — Region: 전라도 — Era: 근대 — Match score bar 71%
- Below: "선택한 문헌으로 레시피 생성하기" Primary Button (full width)
- Secondary: "다시 검색" Ghost Button

[RIGHT PANEL — INPUT SUMMARY]
- Card showing Step 1 selections (read-only):
  - 트렌드 키워드: #쑥라떼
  - 지역: 전라북도
  - 식이 제약: 비건
  - 목표 메뉴: 디저트 음료

[LOADING STATE variant — show as overlay or separate frame]
- Full screen overlay with backdrop blur
- Centered card: spinning indigo circle animation
- Text: "고문헌 데이터를 분석하고 있습니다..."
- Sub-text: "최대 30초가 소요될 수 있습니다"
- Progress dots animating (3 dots)
```

---

## 📄 화면 3 — 레시피 결과 (`/generate` 결과 / Step 3)

```
Design the recipe result screen showing 3 AI-generated recipe candidates.

Screen: Recipe Results — Step 3
Viewport: 1280px desktop.

[HEADER]
- "레시피 생성 완료! 3가지 후보를 확인하세요" (Display)
- Subtitle: "마음에 드는 레시피를 선택해 저장하거나, 더 자세히 살펴보세요"
- Right: "다시 생성" Ghost Button

[3 RECIPE CANDIDATE CARDS — horizontal 3-column grid]

Card 1 (recommended — highlighted with indigo border):
- Top image area: placeholder with gradient (indigo to amber, Korean pattern overlay)
- Tag row: [전라도] [조선후기] [비건]
- Badge: ⭐ 추천
- Title: "전주 쑥 인절미 라떼" (Heading 2)
- Description: "음식디미방의 쑥 조리법을 현대적으로 재해석한 시그니처 음료. 쑥의 쌉싸름한 풍미와 인절미 크림의 달콤함이 조화를 이룹니다."
- Info row: ☕ 난이도 쉬움  |  ⏱ 15분  |  💰 예상원가 ₩1,200
- Source: "출처: 음식디미방 (1670) · 장서각"
- Buttons: "저장하기" Primary | "자세히 보기" Secondary

Card 2:
- Same structure, no highlight border
- Title: "쑥 절편 프라페"
- Tags: [전국] [조선후기] [비건]
- Difficulty: 보통, 20분, ₩1,450

Card 3:
- Title: "쑥 한방 스무디"
- Tags: [경상도] [조선전기] [비건]
- Difficulty: 쉬움, 10분, ₩980

[BOTTOM — source attribution bar]
- Light gray bar: "본 레시피는 공공누리 제1유형 데이터를 활용합니다 · 출처: 장서각, 국립민속박물관"
```

---

## 📋 화면 4 — 레시피 상세 (`/recipes/{id}`)

```
Design the recipe detail screen for "K-Heritage Recipe AI".

Screen: Recipe Detail
Viewport: 1280px desktop, 2-column layout (content left 65% / sidebar right 35%)

[LEFT — MAIN CONTENT]

Header section:
- Breadcrumb: 내 레시피 > 전주 쑥 인절미 라떼
- Title: "전주 쑥 인절미 라떼" (Display)
- Tag row: [전라도] [조선후기] [비건] [approved ✓]
- Meta row: ☕ 쉬움 | ⏱ 15분 | 👤 2인분 | 📅 2026.05.22 생성

Heritage source callout box (amber accent background):
- 📜 고문헌 출처
- "음식디미방 (1670) — 경상도 장계향 저술, 장서각 소장"
- "향토음식 DB — 전주 전통음료 섹션 (문화데이터광장)"

Ingredients table:
- 2-column table: 재료명 | 분량
- Rows: 생쑥 30g, 인절미 크림 80ml, 오트밀크 200ml, 흑당시럽 15ml, 얼음 적당량
- Table has light indigo header row

Cooking steps:
- Numbered list 1–5
- Each step: circle number (indigo) + bold step title + description text
- Step 3 has a "⏱ 5분 대기" badge

Cost breakdown (collapsible section):
- 재료비 ₩1,200 | 소모품 ₩200 | 예상 판매가 ₩5,500 | 원가율 25.5%

SNS Caption section:
- Gray code block style box
- Pre-filled caption text in Korean with hashtags
- "복사" button top-right of box

[RIGHT SIDEBAR]

Action buttons (stacked vertical):
- "PDF 저장" Primary (full width)
- "고증 인증서 발급" Secondary (full width) with Pro badge
- "공유하기" Ghost (full width)

Star rating widget:
- "이 레시피가 도움이 됐나요?"
- 5 stars (interactive)
- "판매 시작했어요" toggle button

Related recipes:
- 2 small recipe cards stacked
```

---

## 📱 모바일 반응형 (선택사항 — 추가 프레임)

```
Create mobile (375px) versions of the Dashboard and Recipe Detail screens from "K-Heritage Recipe AI".

For Dashboard mobile:
- Sidebar navigation becomes bottom tab bar (5 icons)
- Trend chips collapse to horizontal scroll row (show 5–6 visible)
- Recipe cards stack vertically (single column)
- Region filter becomes full-width dropdown at top

For Recipe Detail mobile:
- 2-column layout collapses to single column
- Action buttons move to sticky bottom bar
- Ingredients table becomes scrollable
- Heritage source callout box shows above ingredients

Use the same design system (colors, typography, components) as the desktop screens.
```
