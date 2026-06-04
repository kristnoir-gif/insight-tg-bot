#!/usr/bin/env python3
"""Параметризованный рендер v2-карточек: HTML/CSS поверх готового фона -> PNG bytes.

Принцип: фон (assets/figma/variants_clean/*.png) неизменяемый, поверх кладётся
только динамика, вёрстка через CSS (без ручных координат). Рендер — Playwright.

Пока для пилота — geography. Браузер поднимается на каждый вызов (медленно);
при переходе в прод заменить на персистентный браузер/пул.
"""
from __future__ import annotations

import html as _html
import random
from pathlib import Path

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
BG = ROOT / "assets" / "figma" / "variants_clean"
NEW_BG = ROOT / "new_bg"

W, H = 1080, 1920


def _u(p: Path) -> str:
    _normalize_bg(p)
    return p.resolve().as_uri()


def _normalize_bg(p: Path) -> None:
    """Фоны из Figma иногда экспортируются 1088×1928 (+4px белой каймы с каждой
    стороны — экспорт группы вместо фрейма). Авто-кроп до 1080×1920 при первом
    использовании; оригинал сохраняется как .orig."""
    try:
        if not p.suffix.lower() == ".png" or not p.exists():
            return
        im = Image.open(p)
        if im.size == (1088, 1928):
            import shutil
            shutil.copy(p, str(p) + ".orig")
            im.crop((4, 4, 1084, 1924)).save(p)
            print(f"[bg] {p.name}: 1088×1928 → 1080×1920 (срезана кайма экспорта)")
    except Exception:
        pass


def _plural(n: int, one: str, few: str, many: str) -> str:
    """Русское склонение по числу: 1 раз / 2 раза / 5 раз."""
    n = abs(int(n))
    if 11 <= n % 100 <= 14:
        return many
    d = n % 10
    if d == 1:
        return one
    if 2 <= d <= 4:
        return few
    return many


def _seasons_word(seasons) -> str:
    """«0,4 сезона» (дробь → род.п.) / «1 сезон» / «3 сезона» / «5 сезонов»."""
    s = str(seasons)
    if "," in s or "." in s:
        return "сезона"
    return _plural(int(s or 0), "сезон", "сезона", "сезонов")


_FONT_FACES = f"""
  @font-face {{ font-family:'Inter';
    src:url('{_u(FONTS / "Inter-Variable.ttf")}'); font-weight:100 900; font-style:normal; }}
  @font-face {{ font-family:'Inter';
    src:url('{_u(FONTS / "Inter-Italic-Variable.ttf")}'); font-weight:100 900; font-style:italic; }}
  @font-face {{ font-family:'Nooks';
    src:url('{_u(FONTS / "TT Nooks Script Educational Regular.otf")}'); font-weight:400; font-style:normal; }}
  @font-face {{ font-family:'NooksEdu';
    src:url('{_u(FONTS / "TT Nooks Educational Black.otf")}'); font-weight:900; font-style:normal; }}
  @font-face {{ font-family:'NooksScript';
    src:url('{_u(FONTS / "TT Nooks Script Educational Bold.otf")}'); font-weight:700; font-style:normal; }}
"""


# Авто-фит: после загрузки шрифтов любая группа [data-fit] масштабирует размер
# шрифта строк (.fit) так, чтобы самая широкая влезла в data-fit-max (px по центру).
# Уменьшает только если не влезает; уникальный размер для всей группы (как в макете).
_AUTOFIT = """
<script>
(async () => {
  try { await document.fonts.ready; } catch(e) {}
  document.querySelectorAll('[data-fit]').forEach(group => {
    const maxw = parseFloat(group.dataset.fitMax || '960');
    // data-fit-grow: масштабировать и ВВЕРХ (заполнить maxw); data-fit-cap: предел кегля
    const grow = group.hasAttribute('data-fit-grow');
    const cap = parseFloat(group.dataset.fitCap || '99999');
    const lines = [...group.querySelectorAll('.fit')];
    if (!lines.length) return;
    const widest = Math.max(...lines.map(l => l.getBoundingClientRect().width));
    if (widest > maxw || grow) {
      const rows = group.children;
      const cur = parseFloat(getComputedStyle(rows[0]).fontSize);
      const nf = Math.min(cap, Math.floor(cur * maxw / widest));
      [...rows].forEach(r => r.style.fontSize = nf + 'px');
    }
  });
  // [data-below] — поставить элемент на data-gap px ниже элемента из data-below
  // (data-gap-adj компенсирует leading, чтобы зазор был визуальным между глифами)
  document.querySelectorAll('[data-below]').forEach(el => {
    const ref = document.querySelector(el.dataset.below);
    if (!ref) return;
    const gap = parseFloat(el.dataset.gap || '60');
    const adj = parseFloat(el.dataset.gapAdj || '0');
    el.style.top = (ref.getBoundingClientRect().bottom + gap + adj) + 'px';
  });
  // стопка .hit-card внахлёст: каждая следующая начинается за data-ov px до низа предыдущей.
  // Низ стопки НЕ должен заходить на плашку @insight (y1713) — LIMIT 1690:
  // 1) сначала увеличиваем нахлёст (до +60px), 2) потом режем самый длинный текст.
  const hc = [...document.querySelectorAll('.hit-card')].sort(
    (a, b) => (+a.dataset.order) - (+b.dataset.order));
  if (hc.length) {
    const top0 = parseFloat(hc[0].dataset.top || '418');
    const ovBase = parseFloat(hc[0].dataset.ov || '45');
    const LIMIT = parseFloat(hc[0].dataset.limit || '1690');
    const GAP = 30; // мин. ВИЗУАЛЬНЫЙ зазор: низ текста → верх следующей плашки
    // карточки ПОВЁРНУТЫ → геометрию меряем по getBoundingClientRect (учитывает rotate)
    const layout = () => {
      let y = top0;
      hc.forEach((c, i) => {
        c.style.top = y + 'px';
        if (i > 0) {
          const prevT = hc[i-1].querySelector('.t') || hc[i-1];
          const need = (prevT.getBoundingClientRect().bottom + GAP)
                       - c.getBoundingClientRect().top;
          if (need > 0) { y += need; c.style.top = y + 'px'; }
        }
        y += c.offsetHeight - ovBase;
      });
      return hc[hc.length-1].getBoundingClientRect().bottom;
    };
    let bottom = layout();
    let guard = 40;
    while (bottom > LIMIT && guard--) {
      const ts = hc.map(c => c.querySelector('.t')).filter(Boolean);
      if (!ts.length) break;
      const longest = ts.reduce((a, b) => a.textContent.length >= b.textContent.length ? a : b);
      const cur = longest.textContent.replace(/…$/, '');
      if (cur.length < 60) break;
      longest.textContent = cur.slice(0, cur.length - 12).trimEnd() + '…';
      bottom = layout();
    }
  }
  // ОПТИЧЕСКОЕ центрование текста в плашках (.pill .pv): CSS центрует шрифтовой
  // бокс, а глифы сидят ниже центра. Сдвиг ЕДИНЫЙ для всех плашек карточки:
  // метрики объединяются по всем строкам (max ascent/descent), чтобы тексты
  // стояли на одном уровне (фидбек 05.06 — «выровнять как слово работа»).
  const pvs = [...document.querySelectorAll('.pill .pv')];
  if (pvs.length) {
    const cnv = document.createElement('canvas').getContext('2d');
    const cs = getComputedStyle(pvs[0]);
    cnv.font = cs.fontWeight + ' ' + cs.fontSize + ' ' + cs.fontFamily;
    const mode = (document.querySelector('.pills') || {dataset:{}}).dataset.align || 'union';
    let aA = 0, aD = 0, fm = null;
    if (mode === 'digits') {
      // «в цифрах»: центруем по полосе ЦИФР (cap-высота, без выносных)
      fm = cnv.measureText('0123456789');
      aA = fm.actualBoundingBoxAscent; aD = fm.actualBoundingBoxDescent;
    } else {
      pvs.forEach(s => {
        const m = cnv.measureText(s.textContent);
        aA = Math.max(aA, m.actualBoundingBoxAscent);
        aD = Math.max(aD, m.actualBoundingBoxDescent);
        fm = m;
      });
    }
    const bm = (fm.fontBoundingBoxAscent - fm.fontBoundingBoxDescent) / 2;
    const dy = ((aA - aD) / 2 - bm).toFixed(1);
    pvs.forEach(s => {
      s.style.display = 'inline-block';
      s.style.transform = 'translateY(' + dy + 'px)';
    });
  }
  document.body.dataset.ready = '1';
})();
</script>
"""


def _page_html(bg: str, css: str, body: str) -> str:
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{_FONT_FACES}
  *{{margin:0;padding:0;box-sizing:border-box;}}
  html,body{{width:{W}px;height:{H}px;}}
  /* overscan +10px: срезаем тонкую белую кайму, впечатанную в края некоторых фонов */
  body{{position:relative;background-image:url('{bg}');
    background-size:calc({W}px + 10px) calc({H}px + 10px);
    background-position:center;background-repeat:no-repeat;
    font-family:'Inter',sans-serif;color:#fff;-webkit-font-smoothing:antialiased;}}
{css}
</style></head><body>
{body}
{_AUTOFIT}
</body></html>"""


# ---------------------------------------------------------------------------
# 11 — GEOGRAPHY
# ---------------------------------------------------------------------------
# Девайдер строк (geography/top_person) = фикс. 727px из Figma (не по ширине текста).
# Правило: если найден только 1 параметр — девайдера под ним НЕТ.
_RULE = '<div class="rule"></div>'


def _ranked_rows(items, cap: bool = False, with_num: bool = True,
                 rule_after_last: bool = True) -> str:
    single = len(items) == 1
    n = len(items)
    out = []
    for i, it in enumerate(items):
        if with_num:
            label, cnt = it
            txt = str(label).capitalize() if cap else str(label).lower()
            inner = (f'<span class="city">{_html.escape(txt)}</span> – '
                     f'<span class="num">{int(cnt)}</span>')
        else:
            txt = str(it).capitalize() if cap else str(it).lower()
            inner = _html.escape(txt)
        is_last = (i == n - 1)
        rule = '' if (single or (is_last and not rule_after_last)) else _RULE
        out.append(f'<div class="row"><span class="line fit">{inner}</span>{rule}</div>')
    return "\n".join(out)


_GEO_CSS = """
  .subtitle{position:absolute;top:315px;left:0;width:1080px;text-align:center;
    font-size:44px;font-weight:400;color:#e8e8ec;}
  /* центр блока на y=890 (= центр эталонного 6-строчного блока), чтобы 2-3 города
     красиво вставали в середину, а 6 совпадали с макетом 1:1 */
  .cities{position:absolute;top:890px;left:0;width:1080px;transform:translateY(-50%);
    display:flex;flex-direction:column;align-items:center;}
  .row{display:flex;flex-direction:column;align-items:center;
    font-size:140px;font-weight:500;line-height:0.78;}
  .row .line{display:inline-block;white-space:nowrap;}
  .row .num{font-family:'Nooks';font-weight:400;}
  /* девайдер 727px, на 19px визуальных ниже базовой линии города (хвосты не в счёт);
     line-height 0.78≈фрейм 109/140; margin-top 6 даёт визуальные 19px */
  .row .rule{width:727px;height:4px;background:rgba(255,255,255,0.5);margin:6px 0 23px;}
  .heart{position:absolute;top:1430px;left:0;width:1080px;text-align:center;
    font-size:42px;font-style:italic;color:#e0e0e6;}
"""


def geography_html(top_cities: list[tuple[str, int]], total: int, heart: str) -> str:
    cities = (top_cities or [])[:6]
    rows = _ranked_rows(cities, cap=True)
    # сердце канала пишем только если городов >1 (правило 1-параметра);
    # ставим на 60 визуальных px (между глифами) под последним городом
    heart_html = ""
    if len(cities) > 1:
        heart_html = (
            f'\n<div class="heart" data-below=".cities .row:last-child .line" '
            f'data-gap="60" data-gap-adj="-24">'
            f'сердце канала — {_html.escape(str(heart).capitalize())}</div>'
        )
    body = (
        f'<div class="subtitle">{int(total)} упоминаний городов</div>\n'
        f'<div class="cities" data-fit data-fit-max="960">{rows}</div>'
        f'{heart_html}'
    )
    return _page_html(_u(NEW_BG / "geography.png"), _GEO_CSS, body)


# ---------------------------------------------------------------------------
# Общая «ranked»-раскладка: строки по центру, фикс. девайдер 727px,
# числа — TT Nooks. Используется в 18 top_person и 12 top_phrases.
# top задаётся инлайном (центр блока), transform центрирует по вертикали.
# ---------------------------------------------------------------------------
_RANKED_CSS = """
  .ranked{position:absolute;left:0;width:1080px;transform:translateY(-50%);
    display:flex;flex-direction:column;align-items:center;}
  .ranked .row{display:flex;flex-direction:column;align-items:center;
    font-size:140px;font-weight:500;line-height:0.78;}
  .ranked .row .line{display:inline-block;white-space:nowrap;}
  .ranked .row .num{font-family:'Nooks';font-weight:400;}
  .ranked .row .rule{width:727px;height:4px;background:rgba(255,255,255,0.5);margin:6px 0 23px;}
"""


def top_person_html(people: list[tuple[str, int]]) -> str:
    # девайдер под последней личностью НЕ рисуем (фидбек Кристины 04.06)
    rows = _ranked_rows((people or [])[:6], cap=True, rule_after_last=False)
    body = f'<div class="ranked" style="top:1030px" data-fit data-fit-max="960">{rows}</div>'
    return _page_html(_u(NEW_BG / "top_person.png"), _RANKED_CSS, body)


def top_phrases_html(phrases: list[str]) -> str:
    # блок фраз центрируем между низом заголовка (y349) и звёздочкой (y1525) → центр y937;
    # девайдеры только МЕЖДУ фразами (под последней — нет, как в Figma)
    rows = _ranked_rows((phrases or [])[:6], with_num=False, rule_after_last=False)
    body = f'<div class="ranked" style="top:937px" data-fit data-fit-max="960">{rows}</div>'
    return _page_html(_u(NEW_BG / "top_phrases.png"), _RANKED_CSS, body)


# ---------------------------------------------------------------------------
# 01 — COVER
# ---------------------------------------------------------------------------
# Точная спека из Figma (best.html, overlay совпал): текст — Inter, большое число —
# TT Nooks Script Bold. Координаты/размеры 1:1 из figma_386_1112.json. Всё CENTER.
_COVER_CSS = """
  .slot{position:absolute;text-align:center;}
  /* верхний блок плывёт: RECAP → имя(2 строки) → год — год всегда ПОД именем */
  .topblock{position:absolute;top:199px;left:0;width:1080px;text-align:center;}
  .topblock .title{font-family:'Inter';font-weight:700;font-size:100px;line-height:110px;
    letter-spacing:-4px;text-transform:uppercase;color:#fff;}
  .topblock .period{font-family:'Inter';font-weight:400;font-size:80px;line-height:104px;
    font-style:italic;color:#fff;margin-top:8px;}
  .big{left:55px;top:582px;width:970px;height:639px;display:flex;
    align-items:center;justify-content:center;font-family:'NooksScript';font-weight:700;
    font-size:450px;line-height:639px;letter-spacing:-18px;color:#fff7ff;}
  .rate{left:3px;top:1352px;width:1077px;font-family:'Inter';font-weight:500;
    font-size:50px;line-height:66px;letter-spacing:0;color:#fbfbfb;}  /* было −3.67 (Figma), слишком узко */
  /* плашка-подпись под hero-числом (Figma Suptitle 386:1120: y1129.57 h148.86,
     padding 124×68, radius 128, Inter ExtraBold 50.35 ls-1 UPPER) —
     стиль тот же, что у плашек тем (матовое стекло + кант) */
  .suptitle{position:absolute;top:1130px;left:0;width:1080px;display:flex;
    justify-content:center;}
  .sup-pill{position:relative;box-sizing:border-box;height:149px;display:flex;
    align-items:center;justify-content:center;padding:0 124px;border-radius:128px;
    background:rgba(255,255,255,0.18);backdrop-filter:blur(13px);
    -webkit-backdrop-filter:blur(13px);
    box-shadow:inset 0 2px 8px rgba(216,238,247,0.28);
    font-family:'Inter';font-weight:800;font-size:50px;line-height:1;
    letter-spacing:-1px;text-transform:uppercase;color:#fff7ff;white-space:nowrap;}
  .sup-pill::before{content:'';position:absolute;inset:0;border-radius:inherit;padding:3.5px;
    background:
      radial-gradient(75% 130% at 0% 35%, #98F9FF 0%, rgba(152,249,255,0.5) 30%, rgba(152,249,255,0) 72%),
      radial-gradient(75% 130% at 100% 70%, #EABFFF 0%, rgba(234,191,255,0.5) 30%, rgba(234,191,255,0) 72%);
    -webkit-mask:linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
    -webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none;}
  /* аватарка канала (Figma image 25: x493 y1498 94×94, круг) */
  .avatar{position:absolute;left:493px;top:1498px;width:94px;height:94px;
    border-radius:50%;object-fit:cover;}
"""


def _name_two_lines(name_upper: str) -> str:
    """Имя канала в 2 строки (балансируем по словам). 1 слово — 1 строка."""
    words = _html.escape(name_upper).split()
    if len(words) <= 1:
        return words[0] if words else ""
    mid = (len(words) + 1) // 2
    return " ".join(words[:mid]) + "<br>" + " ".join(words[mid:])


def cover_html(title_upper: str, years: str, hero: str, subtitle: str,
               plaque: str = "ПОСТОВ ЗА ГОД", avatar_uri: str | None = None) -> str:
    avatar = f'<img class="avatar" src="{avatar_uri}">' if avatar_uri else ""
    body = (
        f'<div class="topblock">'
        f'<div class="title">TELEGRAM RECAP<br>{_name_two_lines(title_upper)}</div>'
        f'<div class="period">{_html.escape(years)}</div></div>\n'
        f'<div class="slot big">{_html.escape(hero)}</div>\n'
        f'<div class="suptitle"><span class="sup-pill">{_html.escape(plaque)}</span></div>\n'
        f'<div class="slot rate">{_html.escape(subtitle)}</div>'
        f'{avatar}'
    )
    return _page_html(_u(NEW_BG / "1306010585.png"), _COVER_CSS, body)


# ---------------------------------------------------------------------------
# 04 — SUM OF REACTIONS  (фон: заголовок+сердце+плашка впечатаны)
# ---------------------------------------------------------------------------
# Принцип как most_used (Figma 386:1240, фон new_bg/sum_of_reactions.png):
# заголовок+сердце+плашка «РЕАКЦИЙ ЗА ВСЕ ВРЕМЯ» впечатаны; накладываем большое
# число (в сердце, NooksScript, fill) + «≈ N на пост» под сердцем@1525.
_SUMR_CSS = """
  /* центр глифов 922 = середина зоны «вырез сердца (687) ↔ плашка (1157)»:
     зазоры сверху и снизу равны; кегль крупнее (cap 415) */
  /* диапазон глифов по Кристине: y765..1037 */
  .hero-r{position:absolute;top:728px;left:0;width:1080px;height:380px;
    display:flex;align-items:center;justify-content:center;}
  .hero-r .fit{font-family:'NooksScript';font-weight:700;font-size:320px;
    line-height:1;letter-spacing:-6px;}
  .sub-r{position:absolute;top:1525px;left:0;width:1080px;text-align:center;
    font-weight:500;font-size:46px;color:#eaf0ff;}
"""


def sum_reactions_html(total_str: str, per_post_str: str) -> str:
    body = (
        f'<div class="hero-r" data-fit data-fit-grow data-fit-max="700" data-fit-cap="388">'
        f'<span class="fit">{_html.escape(str(total_str))}</span></div>\n'
        f'<div class="sub-r">{_html.escape(str(per_post_str))}</div>'
    )
    return _page_html(_u(NEW_BG / "sum_of_reactions.png"), _SUMR_CSS, body)


# ---------------------------------------------------------------------------
# 17 — MOST USED WORD  (фон: заголовок+сердце+ПУСТАЯ плашка впечатаны)
# ---------------------------------------------------------------------------
_MUW_CSS = """
  /* слово — шрифтом заголовка (NooksScript Bold), поля 80px → max-width 920px,
     растёт вверх до предела (data-fit-grow), кэп кегля 380px. Флекс-контейнер с
     центром на y=904 (top 714 + height 380/2) — центр держится при любом кегле */
  .hero-w{position:absolute;top:727px;left:0;width:1080px;height:380px;
    display:flex;align-items:center;justify-content:center;}
  .hero-w .fit{font-family:'NooksScript';font-weight:700;font-size:320px;
    line-height:1;letter-spacing:-2px;}
  /* «упомянуто N раз» — центр впечатанной плашки (флекс по обеим осям),
     центр надписи на y=1176 (height 162 → top 1095); ширина текста ≈73% плашки */
  .pill-w{position:absolute;top:1095px;left:163px;width:754px;height:162px;
    display:flex;align-items:center;justify-content:center;}
  .pill-w .fit{font-weight:800;font-size:90px;letter-spacing:1px;
    text-transform:uppercase;white-space:nowrap;}
"""


def most_used_html(word: str, count: int) -> str:
    body = (
        f'<div class="hero-w" data-fit data-fit-grow data-fit-max="920" data-fit-cap="380"><span class="fit">{_html.escape(word.upper())}</span></div>\n'
        f'<div class="pill-w" data-fit data-fit-max="550"><span class="fit">упомянуто {int(count)} {_plural(count, "раз", "раза", "раз")}</span></div>'
    )
    return _page_html(_u(NEW_BG / "the_most_used_word.png"), _MUW_CSS, body)


# ---------------------------------------------------------------------------
# 03 — CHANAL IN NUMBERS  (фон: только сердце + нижняя плашка; заголовок НЕ впечатан)
# плашки-«таблетки» каскадом по центру (flex-wrap), форму сердца задаёт фон
# ---------------------------------------------------------------------------
_PILLS_CSS = """
  .cn-title{position:absolute;top:140px;left:0;width:1080px;text-align:center;
    font-family:'NooksEdu';font-weight:900;font-size:140px;line-height:0.98;text-transform:uppercase;}
  .cn-sub{position:absolute;top:455px;left:0;width:1080px;text-align:center;
    font-weight:400;font-size:54px;color:#e8e8ec;}
  /* плашки центрируются по вертикали внутри сердца (height = коробка сердца),
     чтобы при малом числе плашек они не висели вверху, а сидели по центру */
  .pills{position:absolute;left:90px;width:900px;
    display:flex;flex-wrap:wrap;justify-content:center;align-content:flex-start;
    gap:36px 20px;}
  /* матовая плашка как в макете: розовое сердце просвечивает + голубой кант #bdd4e4
     (ярче сверху, через градиентный border-image) + блик сверху */
  .pill{position:relative;background:rgba(255,255,255,0.18);
    border-radius:70px;padding:24px 54px;font-size:67px;font-weight:500;line-height:1;color:#fff;
    white-space:nowrap;backdrop-filter:blur(13px);-webkit-backdrop-filter:blur(13px);
    box-shadow:inset 0 2px 8px rgba(216,238,247,0.28);}
  /* кант = 2 радиальные обводки из Figma: #98F9FF (голубая) + #EABFFF (сиреневая),
     каждая в прозрачность; рисуем кольцо через mask, скругление сохраняется */
  .pill::before{content:'';position:absolute;inset:0;border-radius:inherit;padding:3.5px;
    background:
      radial-gradient(75% 130% at 0% 35%, #98F9FF 0%, rgba(152,249,255,0.5) 30%, rgba(152,249,255,0) 72%),
      radial-gradient(75% 130% at 100% 70%, #EABFFF 0%, rgba(234,191,255,0.5) 30%, rgba(234,191,255,0) 72%);
    -webkit-mask:linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
    -webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none;}
"""


def _pills_block(pills: list[str], top: int, height: int = 700,
                 align: str = "union") -> str:
    # height = коробка сердца; align-content:center центрирует плашки по вертикали.
    # текст обёрнут в .pv — JS-центровка глифов по canvas-метрикам (см. _AUTOFIT).
    # align: "union" (по всем строкам) | "digits" (по цифрам — карточка «в цифрах»)
    items = "".join(f'<span class="pill"><span class="pv">{_html.escape(str(p))}</span></span>'
                    for p in pills)
    return (f'<div class="pills" data-align="{align}" '
            f'style="top:{top}px;height:{height}px">{items}</div>')


def chanal_in_numbers_html(title_upper: str, pills: list[str]) -> str:
    # Figma 386:1187: название (2 строки, NooksEdu) @y173; «в цифрах» Inter50 @y435;
    # плашки Inter500 67 с кантом, старт 715. Заголовок в фоне НЕ впечатан.
    # заголовок+подпись единым блоком: подпись flow'ится под заголовком с
    # фикс. зазором 37px (глобальное правило), не зависит от 1/2 строк имени
    css = _PILLS_CSS + (
        "\n  .cn-head{position:absolute;top:173px;left:0;width:1080px;text-align:center;}"
        "\n  .cn-head .cn-title{position:static;font-family:'NooksScript';font-weight:700;"
        "font-size:120px;line-height:1.0;}"
        "\n  .cn-head .cn-title .fit{display:block;}"
        # видимый зазор 37px: −5 компенсирует пустой leading строк (бокс шрифта > глифов)
        "\n  .cn-head .cn-sub{position:static;margin-top:-5px;font-size:50px;}"
    )
    lines = _name_two_lines(title_upper).split("<br>")
    name_html = "".join(f'<span class="fit">{ln}</span>' for ln in lines)
    body = (
        f'<div class="cn-head">'
        f'<div class="cn-title" data-fit data-fit-max="960">{name_html}</div>'
        f'<div class="cn-sub">в цифрах</div></div>\n'
        f'{_pills_block(pills, 715, 690, align="digits")}'
    )
    return _page_html(_u(NEW_BG / "chanal_in_numbers.png"), css, body)


# ---------------------------------------------------------------------------
# 02 — MAIN THEMES  (фон: сердце + плашка; заголовок «ГЛАВНЫЕ ТЕМЫ» НЕ впечатан)
# ---------------------------------------------------------------------------
def main_themes_html(channel_name: str, topics: list[str]) -> str:
    import re
    # составные темы («психология и аутизм») разбиваем на отдельные плашки, всё строчными
    pills, seen = [], set()
    for t in (topics or []):
        for part in re.split(r"\s+и\s+|\s*[,/]\s*", str(t)):
            p = part.strip().lower()
            if p and p not in seen:
                seen.add(p); pills.append(p)
    pills = pills[:10]
    # ВАЖНО: в new_bg/main_themes.png заголовок «ГЛАВНЫЕ ТЕМЫ» УЖЕ впечатан —
    # накладываем только динамику: имя канала (Inter 50 @y321) + плашки (Inter ~64).
    css = _PILLS_CSS + "\n  .cn-sub{top:321px;font-size:50px;}"
    body = (
        f'<div class="cn-sub">{_html.escape(str(channel_name))}</div>\n'
        f'{_pills_block(pills, 715, 690)}'
    )
    return _page_html(_u(NEW_BG / "main_themes.png"), css, body)


# ---------------------------------------------------------------------------
# 16 — READING STATISTICS  (фон: заголовок + пустая стеклянная панель впечатаны)
# ---------------------------------------------------------------------------
# Позиции из Figma (frame 386:1485, панель y553..1465): hero@625, девайдер@956 и
# @1304 (w739), параграф между девайдерами, подпись@1358. Всё центрировано (x540).
_READ_CSS = """
  /* большое число + единица на ОДНОЙ базовой линии (flex baseline) */
  /* координаты 1:1 с jpeg-макета 04.06: глифы hero y686..827 (h140), x208..871
     (w663) → кегль 197px, трекинг −9px (подобраны пиксельным фитом), top 667 */
  .read-hero{position:absolute;top:667px;left:0;width:1080px;height:291px;
    display:flex;align-items:baseline;justify-content:center;
    font-family:'NooksScript';font-weight:700;font-size:197px;line-height:1;}
  .read-hero .fit{font-size:197px;letter-spacing:-9px;white-space:nowrap;}
  .read-hero .n{font-size:inherit;font-family:'NooksScript';font-weight:700;}
  .read-hero .u{font-size:inherit;font-family:'NooksScript';font-weight:700;margin-left:28px;}
  /* девайдер — картинка new_bg/Line.png (градиент с затуханием по краям), w739 */
  .read-div{position:absolute;left:170px;width:739px;height:4px;
    background-repeat:no-repeat;background-size:739px 4px;}
  /* макет Кристины 04.06 (v2): hero «25 часов» → «чтобы прочитать канал за год»
     (центр ~975) → девайдер @1122 → «это как N страниц книжного текста /
     или X сезона сериала» (3 строки, центр ~1256) */
  .read-sub{position:absolute;top:866px;left:170px;width:740px;height:190px;
    display:flex;align-items:center;justify-content:center;text-align:center;
    font-weight:500;font-size:76px;line-height:1.3;}  /* межстрочка как в макете */
  /* подпись центрирована между девайдером (1122) и низом плашки (1465):
     зазор сверху и снизу одинаковый */
  .read-cap{position:absolute;top:1122px;left:170px;width:740px;height:343px;
    display:flex;align-items:center;justify-content:center;
    text-align:center;font-weight:500;font-size:52px;line-height:1.26;color:#ffffff;}
"""


def reading_html(hours, unit_word: str, pages: int, compare: str) -> str:
    """Макет Кристины 04.06 (v2): hero «25 часов» (слово целиком, одним кеглем)
    → «чтобы прочитать канал за год» → девайдер → «это как N страниц книжного
    текста или {compare}». compare: «1 сезон сериала» / «полсезона сериала»."""
    line = _u(NEW_BG / "Divider.png")
    pages = int(pages or 1)
    body = (
        f'<div class="read-hero" data-fit data-fit-max="655"><span class="fit">'
        f'<span class="n">{_html.escape(str(hours))}</span>'
        f'<span class="u">{_html.escape(unit_word)}</span></span></div>\n'
        f'<div class="read-sub">чтобы прочитать канал за год</div>\n'
        f'<div class="read-div" style="top:1122px;background-image:url(\'{line}\')"></div>\n'
        f'<div class="read-cap">это как {pages} '
        f'{_plural(pages, "страница", "страницы", "страниц")} книжного текста<br>'
        f'или {_html.escape(compare)}</div>'
    )
    return _page_html(_u(NEW_BG / "reading_statisticks.png"), _READ_CSS, body)


# ---------------------------------------------------------------------------
# 06 — CHRONOTYPE (×9 вариантов; имя+фигура+плашка впечатаны в фон,
# накладываем только «пик активности XX:00»). bg выбирается по архетипу.
# ---------------------------------------------------------------------------
# bg-файлы в new_bg/ (правильный Figma-экспорт; кот/хаос с другим неймингом)
CHRONO_BG = {
    "Волк": "chronotype_wolf.png", "Сова": "chronotype_owl.png",
    "Лунатик": "chronotype_lunatik.png", "Жаворонок": "chronotype_lark.png",
    "Синица": "chronotype_tit.png", "Белочка": "chronotype_squirrel.png",
    "Кот": "chronotype-cat.png", "Лиса": "chronotype_fox.png",
    "Хроно-хаос": "chronotype_chrono_chaos.png",
}
# Блок внизу (Figma 386:1885, Component 15 @y1442): пик@1442, девайдер@1533 (w829),
# вторичная строка@1561. Тема (цвет текста + девайдер) зависит от яркости фона:
# светлые фоны (Кот) → тёмный текст + Line.png; остальные → белый + Line-white.png.
_CHRONO_CSS = """
  .chrono-peak{position:absolute;top:1442px;left:0;width:1080px;text-align:center;
    font-weight:700;font-size:62px;}
  .chrono-div{position:absolute;top:1533px;left:50%;transform:translateX(-50%);
    width:829px;height:4px;background-repeat:no-repeat;background-size:829px 4px;}
  .chrono-sec{position:absolute;top:1561px;left:0;width:1080px;text-align:center;
    font-weight:500;font-size:44px;line-height:1.18;}
"""
# тема по архетипу: (цвет текста, цвет вторичной строки, файл девайдера)
_CHRONO_DARK = ("#ffffff", "#eaf0ff", "Line-white.png")   # тёмный фон → белый текст
_CHRONO_THEME = {
    # светлый фон → текст цветом заголовка (тёмный) + чёрный девайдер Line_black.png
    "Кот": ("#1f2038", "#1f2038", "Line_black.png"),
}


def _peak_phrase(hour) -> str:
    h = int(hour) % 24
    if 0 <= h < 5:
        return "после полуночи"
    if 5 <= h < 11:
        return "утром"
    if 11 <= h < 17:
        return "днём"
    if 17 <= h < 23:
        return "вечером"
    return "ночью"


def chronotype_html(archetype: str, peak_hour, bucket_share=None) -> str:
    bg = CHRONO_BG.get(archetype, "chronotype_wolf.png")
    text_c, sec_c, div_file = _CHRONO_THEME.get(archetype, _CHRONO_DARK)
    peak = f"{int(peak_hour):02d}:00"
    parts = [f'<div class="chrono-peak" style="color:{text_c}">пик активности {peak}</div>']
    if bucket_share:
        div = _u(NEW_BG / div_file)
        parts.append(f'<div class="chrono-div" style="background-image:url(\'{div}\')"></div>')
        parts.append(
            f'<div class="chrono-sec" style="color:{sec_c}">{int(round(float(bucket_share)))}% '
            f'твоих постов написано {_peak_phrase(peak_hour)}</div>'
        )
    return _page_html(_u(NEW_BG / bg), _CHRONO_CSS, "\n".join(parts))


# ---------------------------------------------------------------------------
# 05 — VOCAB ARCHETYPE (×8). Имя+фигура+«норма»+плашка впечатаны; накладываем
# только «N уникальных слов». bg по уровню (порог по unique_count).
# ---------------------------------------------------------------------------
# bg-файлы в new_bg/ (правильный Figma-экспорт)
VOCAB_BG = {
    "less_6000": "less_6000_ARCHETYPE_by_vocabulary.png",
    "Интеллектуал": "ARCHETYPE_by_vocabulary_Intellectual.png",
    "Мастер слова": "Master of Words_ARCHETYPE_by_vocabulary.png",
    "Лингвист": "Linguist-ARCHETYPE_by_vocabulary.png",
    "Поэт": "Poet_ARCHETYPE_by_vocabulary.png",
    "Писатель": "Writer_ARCHETYPE_by_vocabulary.png",
    "Великий писатель": "The_greate_writer-ARCHETYPE_by_vocabulary.png",
    "Лексический титан": "ARCHETYPE_by_vocabulary.png",
}
# Figma 386:1726: число + «уникальных слов»; блок ВИЗУАЛЬНО (по глифам) центрирован
# между верхом карточки (y0) и верхушкой звезды (~y512 в less_6000): центр глифов
# y≈256. Глифы блока 231px → верх числа -82px от старого (203→121, 391→309).
_VOCAB_CSS = """
  /* +25px оптическая компенсация: свечение над звездой поднимает её визуальный
     край, чисто математический центр (121/309) выглядел чуть высоко */
  .vocab-num{position:absolute;top:146px;left:0;width:1080px;text-align:center;
    font-family:'NooksScript';font-weight:700;font-size:215px;line-height:1;color:#fff;}
  .vocab-sub{position:absolute;top:334px;left:0;width:1080px;text-align:center;
    font-weight:400;font-style:italic;font-size:54px;color:#e8e8ec;}
"""


def vocab_html(bg_file: str, count_str: str) -> str:
    body = (
        f'<div class="vocab-num">{_html.escape(str(count_str))}</div>\n'
        f'<div class="vocab-sub">уникальных слов</div>'
    )
    return _page_html(_u(NEW_BG / bg_file), _VOCAB_CSS, body)


# ---------------------------------------------------------------------------
# 10 — TOXICITY ARCHETYPE (×7). Имя+фигура+плашка впечатаны; накладываем
# 2 строки статистики мата. bg по уровню (порог по mat %).
# ---------------------------------------------------------------------------
_TOX_CSS = """
  .tox-line{position:absolute;left:0;width:1080px;text-align:center;
    font-size:56px;font-weight:800;line-height:1.32;text-transform:uppercase;color:#fff;}
"""
# нижняя надпись: Ангел/Светлый → y1458; остальные (Прямой/Острый/Ядовитый/Ядерный/Дотер) → y1430
_TOX_TOP_1458 = {"tox_angel.png", "tox_light.png"}


def toxicity_html(bg_file: str, mat_pct, posts_pct) -> str:
    top = 1458 if bg_file in _TOX_TOP_1458 else 1430
    body = (f'<div class="tox-line" style="top:{top}px">'
            f'мат {_html.escape(str(mat_pct))}% от всего текста<br>'
            f'{_html.escape(str(posts_pct))}% постов с матом</div>')
    return _page_html(_u(BG / bg_file), _TOX_CSS, body)


# ---------------------------------------------------------------------------
# 16 — ARCHETYPE (общая карточка архетипа канала, ×12). Имя+тэглайн+фигура
# впечатаны в фон (new_bg/ARCHETYPE*.png); накладываем нижнее описание @y1397.
# ---------------------------------------------------------------------------
# Маппинг юнгианского архетипа → файл фона (имена впечатаны в new_bg/ARCHETYPE*.png).
# Прочитано из фонов; ⚠️ -3..-11 Кристина ещё обновляет (могут быть дубли/сдвиги).
# Фоны ARCHETYPE1..12 (Кристина перевыгрузила все 12, описания ВПЕЧАТАНЫ в фон).
ARCH_BG = {
    "Мудрец": "ARCHETYPE1.png", "Искатель": "ARCHETYPE2.png", "Простодушный": "ARCHETYPE3.png",
    "Бунтарь": "ARCHETYPE4.png", "Борец": "ARCHETYPE5.png", "Творец": "ARCHETYPE6.png",
    "Славный малый": "ARCHETYPE7.png", "Любовник": "ARCHETYPE8.png", "Шут": "ARCHETYPE9.png",
    "Опекун": "ARCHETYPE10.png", "Правитель": "ARCHETYPE11.png", "Маг": "ARCHETYPE12.png",
}
# Оверлей-описание для архетипов, у фона которых описание НЕ впечатано (напр. Мудрец).
# У остальных описание уже в фоне → оверлей не нужен.
# ---------------------------------------------------------------------------
# 20 — АНГЛИЦИЗМЫ (новая карточка). Своего new_bg пока нет → собираем в HTML
# (CSS-градиент-фон). % считается в analyzer (anglicism_percent + top_anglicisms).
# ---------------------------------------------------------------------------
_ANGL_CSS = """
  .an-title{position:absolute;top:205px;left:0;width:1080px;text-align:center;
    font-family:'NooksScript';font-weight:700;font-size:118px;line-height:1;
    text-transform:uppercase;color:#fff;}
  .an-sub{position:absolute;top:360px;left:0;width:1080px;text-align:center;
    font-weight:400;font-style:italic;font-size:52px;color:#e6e6ec;}
  .an-num{position:absolute;top:720px;left:0;width:1080px;height:380px;
    display:flex;align-items:center;justify-content:center;
    font-family:'NooksScript';font-weight:700;font-size:360px;line-height:1;color:#fff;}
  .an-cap{position:absolute;top:1175px;left:90px;width:900px;text-align:center;
    font-weight:500;font-size:58px;line-height:1.15;color:#fff;}
  .an-top{position:absolute;top:1420px;left:90px;width:900px;text-align:center;
    font-weight:400;font-size:46px;line-height:1.2;color:#cfd0da;}
  .an-top b{font-weight:700;color:#fff;}
  .an-insight{position:absolute;top:1742px;left:0;width:1080px;text-align:center;
    font-weight:600;font-size:30px;letter-spacing:1px;color:#e8e8ec;opacity:0.85;}
"""


def anglicism_html(pct, top_anglicisms: list | None = None) -> str:
    pct_str = (f"{float(pct):.1f}".rstrip("0").rstrip(".") or "0").replace(".", ",") + "%"
    top_anglicisms = top_anglicisms or []
    words = [str(w) for w, _ in top_anglicisms[:3]]
    top_line = ""
    if words:
        joined = " · ".join(_html.escape(w) for w in words)
        top_line = f'<div class="an-top">чаще всего: <b>{joined}</b></div>'
    body = (
        '<div class="an-title">англицизмы</div>\n'
        '<div class="an-sub">в твоей речи</div>\n'
        f'<div class="an-num">{pct_str}</div>\n'
        '<div class="an-cap">слов — заимствования<br>из английского</div>\n'
        f'{top_line}\n'
        '<div class="an-insight">@INSIGHT_TG_BOT</div>'
    )
    bg_css = "background:radial-gradient(120% 85% at 50% 33%,#2a3a6b 0%,#1a2040 50%,#0c0a1e 100%);"
    return _page_html("", _ANGL_CSS, body).replace("background-image:url('');", bg_css, 1)


# Облако англицизмов — какие заимствования в ходу чаще всего (по top_anglicisms).
_ANGLCLOUD_CSS = """
  .ac-title{position:absolute;top:200px;left:0;width:1080px;text-align:center;
    font-family:'NooksScript';font-weight:700;font-size:110px;line-height:1;
    text-transform:uppercase;color:#fff;}
  .ac-sub{position:absolute;top:345px;left:0;width:1080px;text-align:center;
    font-weight:400;font-style:italic;font-size:50px;color:#e6e6ec;}
  .ac-img{position:absolute;top:470px;left:50%;transform:translateX(-50%);
    height:1110px;width:auto;}
  .ac-insight{position:absolute;top:1742px;left:0;width:1080px;text-align:center;
    font-weight:600;font-size:30px;letter-spacing:1px;color:#e8e8ec;opacity:0.85;}
"""


def anglicism_cloud_html(cloud_png: str | Path) -> str:
    body = (
        '<div class="ac-title">англицизмы</div>\n'
        '<div class="ac-sub">что заимствуешь чаще всего</div>\n'
        f'<img class="ac-img" src="{_u(Path(cloud_png))}">\n'
        '<div class="ac-insight">@INSIGHT_TG_BOT</div>'
    )
    bg_css = "background:radial-gradient(120% 85% at 50% 40%,#2a3a6b 0%,#1a2040 50%,#0c0a1e 100%);"
    return _page_html("", _ANGLCLOUD_CSS, body).replace("background-image:url('');", bg_css, 1)


def archetype_html(archetype: str) -> str:
    # описание + имя + фигура впечатаны в фон → накладывать ничего не нужно
    bg = ARCH_BG.get(str(archetype).strip().capitalize(), "ARCHETYPE1.png")
    return _page_html(_u(NEW_BG / bg), "", "")


# ---------------------------------------------------------------------------
# 11 — CHANAL IN ONE PHRASE (386:1436). Фона в new_bg НЕТ → строим целиком в HTML:
# градиент-фон + заголовок + стеклянная панель + AI-фраза. Точный new_bg — позже.
# ---------------------------------------------------------------------------
# Фон new_bg/chanal_in_one_phrase.png: заголовок+панель+«AI прочитал всё и подумал»+
# девайдер@823+звезда+@insight ВПЕЧАТАНЫ. Накладываем только AI-фразу (в панель под
# девайдером, центр панели 557..1469).
_OP_CSS = """
  .op-phrase{position:absolute;top:823px;left:170px;width:740px;height:646px;
    display:flex;align-items:center;justify-content:center;text-align:center;
    font-weight:500;font-size:56px;line-height:1.2;color:#fff;}
"""


def chanal_in_one_phrase_html(phrase: str) -> str:
    body = f'<div class="op-phrase">{_html.escape(_no_hanging(phrase))}</div>'
    return _page_html(_u(NEW_BG / "chanal_in_one_phrase.png"), _OP_CSS, body)
# накладываем: название палитры, hero-эмодзи, счётчик, полоску эмодзи, подписи
# ---------------------------------------------------------------------------
# Позиции из Figma (frame 386:1401, плашка y527..1539): name@589, hero-центр@919,
# count@1159, девайдер w615@1271, строка эмодзи@1330. Зазоры count→девайдер→строка ≈56px.
_EMO_CSS = """
  /* название палитры: 65px поля от краёв плашки (x148..931) → ширина 653px, fill */
  .emo-name{position:absolute;top:589px;left:0;width:1080px;text-align:center;
    font-weight:500;font-size:72px;color:#fff;}
  .emo-name .fit{display:inline-block;white-space:nowrap;}
  /* большой эмодзи занимает y742..1144 (height 402); картинкой — 380px,
     чтобы не наезжал на «N раз» (глиф 430px выступал за бокс) */
  .emo-hero{position:absolute;top:742px;left:0;width:1080px;height:402px;
    display:flex;align-items:center;justify-content:center;font-size:380px;line-height:1;}
  .emo-hero img{width:380px;height:380px;}
  .emo-count{position:absolute;top:1159px;left:0;width:1080px;text-align:center;
    font-weight:400;font-size:48px;color:#ececf2;}
  .emo-divider{position:absolute;top:1271px;left:50%;transform:translateX(-50%);
    width:615px;height:3px;background:rgba(255,255,255,0.5);}
  /* девайдер + 4 эмодзи + подписи — одной ширины (615px): сетка из 4 равных колонок,
     подпись по центру под своим эмодзи */
  .emo-grid{position:absolute;top:1330px;left:50%;transform:translateX(-50%);
    width:615px;display:flex;}
  .emo-col{flex:1;display:flex;flex-direction:column;align-items:center;}
  .emo-col .e{font-size:96px;line-height:1;}
  .emo-col .l{font-weight:400;font-size:34px;color:#cfd0da;margin-top:20px;white-space:nowrap;}
"""


_EMOJI_CACHE = Path(__file__).resolve().parent / "emoji_cache"


def _emoji_fetch(url: str, dst: Path) -> bool:
    try:
        import ssl, certifi, urllib.request
        ctx = ssl.create_default_context(cafile=certifi.where())
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        dst.write_bytes(urllib.request.urlopen(req, timeout=15, context=ctx).read())
        return True
    except Exception:
        return False


def _emoji_png(emoji: str, px: int = 402) -> "Path | None":
    """Большой эмодзи картинкой 512px (Facebook-сет с Emojipedia — единственный
    с исходниками >160px, стиль глянцевый ~Apple) с ДАУНскейлом до px — чёткие
    края. Фолбэк: Apple 160 (emojicdn) с апскейлом. Нет сети/кэша — None (глиф).
    Apple Color Emoji крупнее 160px не существует в природе (битмап-шрифт)."""
    base = (emoji or "").replace("️", "")
    if not base:
        return None
    key = "-".join(f"{ord(c):x}" for c in base)
    _EMOJI_CACHE.mkdir(exist_ok=True)
    out = _EMOJI_CACHE / f"{key}_{px}.png"
    if out.exists():
        return out

    src = _EMOJI_CACHE / f"{key}_512.png"
    if not src.exists():
        try:  # слаг эмодзипедии: имя из demojize + кодпоинты
            import emoji as emoji_lib
            name = emoji_lib.demojize(emoji).strip(":").replace("_", "-").lower()
            hex_novs = "-".join(f"{ord(c):x}" for c in emoji if ord(c) != 0xFE0F)
            hex_all = "-".join(f"{ord(c):x}" for c in emoji)
            for sl in (f"{name}_{hex_novs}", f"{name}_{hex_all}"):
                if _emoji_fetch(f"https://em-content.zobj.net/source/facebook/355/{sl}.png", src):
                    break
        except Exception:
            pass
    if not src.exists():  # фолбэк: Apple 160 (будет мягче)
        src = _EMOJI_CACHE / f"{key}_160.png"
        if not src.exists():
            import urllib.parse
            if not _emoji_fetch("https://emojicdn.elk.sh/" + urllib.parse.quote(emoji)
                                + "?style=apple", src):
                return None
    try:
        from PIL import Image
        im = Image.open(src).convert("RGBA").resize((px, px), Image.LANCZOS)
        im.save(out)
        return out
    except Exception:
        return None


# Emoji с «текстовым» дефолтом (❤, ♥ и т.п.) без VS16 рендерятся контурным глифом.
# Добавляем U+FE0F, чтобы форсить цветной emoji-рендер.
_TEXT_DEFAULT_EMOJI = {"❤", "♥", "♠", "♣", "♦",
                       "☺", "☹", "✌", "☝", "✍", "❣"}


def _color_emoji(e: str) -> str:
    base = (e or "").replace("️", "")
    return base + "️" if base in _TEXT_DEFAULT_EMOJI else e


def emotions_html(palette_name: str, hero_emoji: str, count: str,
                  strip_emojis: list[str], labels: list[str]) -> str:
    hero_png = _emoji_png(hero_emoji)
    hero = (f'<img src="{hero_png.as_uri()}">' if hero_png
            else _color_emoji(hero_emoji))
    emojis = [_color_emoji(e) for e in (strip_emojis or [])]
    labs = (labels or []) + [""] * (len(emojis) - len(labels or []))
    cols = "".join(
        f'<div class="emo-col"><span class="e">{e}</span>'
        f'<span class="l"{chr(32)+"style=font-size:26px" if len(str(labs[i])) > 9 else ""}>'
        f'{_html.escape(str(labs[i]))}</span></div>'
        for i, e in enumerate(emojis)
    )
    body = (
        f'<div class="emo-name" data-fit data-fit-grow data-fit-max="653" data-fit-cap="120">'
        f'<span class="fit">{_html.escape(str(palette_name))}</span></div>\n'
        f'<div class="emo-hero">{hero}</div>\n'
        f'<div class="emo-count">{_html.escape(str(count))} раз</div>\n'
        f'<div class="emo-divider"></div>\n'
        f'<div class="emo-grid">{cols}</div>'
    )
    return _page_html(_u(NEW_BG / "emotions.png"), _EMO_CSS, body)


# ---------------------------------------------------------------------------
# 15 — HIT POST  (фон: заголовок+подзаголовок+плашка впечатаны; накладываем
# 3 стеклянные карточки постов внахлёст). posts = [(reactions, text, date), ...]
# ---------------------------------------------------------------------------
# Стеклянные карточки (Figma 386:1466): радиальный белый градиент 0→0.5 к краям,
# кант #98F9FF+#EABFFF (как плашки), backdrop-blur, тени, скругление 33, лёгкий поворот.
_HIT_CSS = """
  /* высота фрейма авто; нижний паддинг больше нахлёста — чтобы перекрывался
     только пустой низ, а не дата/текст */
  .hit-card{position:absolute;border-radius:33px;padding:44px 52px 74px;
    display:flex;flex-direction:column;color:#fff;
    background:radial-gradient(125% 125% at 50% 45%,
      rgba(235,235,235,0) 0%, rgba(235,235,235,0.22) 23%, rgba(235,235,235,0.5) 100%);
    backdrop-filter:blur(40px);-webkit-backdrop-filter:blur(40px);
    box-shadow:0 34px 34px rgba(0,0,0,0.10),0 14px 14px rgba(0,0,0,0.05);}
  .hit-card::before{content:'';position:absolute;inset:0;border-radius:inherit;padding:2.8px;
    background:
      radial-gradient(80% 130% at 0% 0%, #98F9FF 0%, rgba(152,249,255,0.5) 28%, rgba(152,249,255,0) 70%),
      radial-gradient(80% 130% at 100% 100%, #EABFFF 0%, rgba(234,191,255,0.5) 28%, rgba(234,191,255,0) 70%);
    -webkit-mask:linear-gradient(#fff 0 0) content-box,linear-gradient(#fff 0 0);
    -webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none;}
  /* шапка: «N реакций» слева, дата справа; ОДИН кегль 41px (среднее 56/26),
     выравнивание по верхней линии; цвет/начертание свои */
  .hit-card .hd{display:flex;justify-content:space-between;align-items:flex-start;}
  .hit-card .r{font-weight:800;font-size:41px;line-height:1;}
  .hit-card .d{font-weight:400;font-size:41px;line-height:1;color:#ead8e6;
    margin-left:30px;white-space:nowrap;}
  .hit-card .t{font-weight:500;font-size:44px;line-height:1.14;margin-top:20px;}
"""
# визуальный порядок сверху вниз; top расставляет JS-стопка (внахлёст data-ov).
# z ВОЗРАСТАЕТ вниз (нижняя карточка спереди) — перекрывает только пустой низ верхней,
# поэтому текст/дата не загораживаются. (left, w, rot, индекс поста, z)
_HIT_SLOTS = [
    (160, 810, 2.19, 1, 1),    # A — верхняя
    (88, 832, -4.95, 0, 2),    # B — большая середина
    (140, 800, 1.62, 2, 3),    # C — нижняя (спереди); расширена 597→800, чтоб текст не теснился
]
_HIT_START_TOP = 418  # старт первой карточки (Figma)
_HIT_OVERLAP = 38     # нахлёст < нижнего паддинга (56) → перекрывается только пустой низ
_HIT_BOTTOM_LIMIT = 1663  # низ стопки: ≥50px до плашки @insight (y1713)


# Короткие предлоги/союзы, которые нельзя оставлять висеть в конце строки —
# привязываем к следующему слову неразрывным пробелом ( ).
_HANG_LONG = {"для", "под", "над", "при", "без", "про", "или", "что",
              "как", "чем", "это", "эта", "так", "уже", "его", "её"}


def _no_hanging(text: str) -> str:
    """Привязывает короткие предлоги/союзы к след. слову (нет висячих в конце строки)."""
    words = str(text).split()
    if not words:
        return ""
    out = words[0]
    for i in range(1, len(words)):
        prev = words[i - 1].strip(".,!?;:—–()«»\"'").lower()
        sep = " " if (len(prev) <= 2 or prev in _HANG_LONG) else " "
        out += sep + words[i]
    return out


def _truncate(text: str, limit: int = 144) -> str:
    """Обрезаем длинный пост до limit символов (как твит) + многоточие."""
    s = str(text).strip()
    if len(s) <= limit:
        return s
    return s[:limit].rstrip() + "…"


def hit_post_html(posts: list[tuple]) -> str:
    posts = (posts or [])[:3]
    cards = []
    for order, (left, w, rot, idx, z) in enumerate(_HIT_SLOTS):
        if idx >= len(posts):
            continue
        reactions, text, date = posts[idx]
        text = _truncate(text, 144)
        try:
            n = int(reactions)
            r_label = f"{n} {_plural(n, 'реакция', 'реакции', 'реакций')}"
        except (TypeError, ValueError):
            r_label = str(reactions)
        meta = (f' data-top="{_HIT_START_TOP}" data-ov="{_HIT_OVERLAP}" data-limit="{_HIT_BOTTOM_LIMIT}"'
                if order == 0 else "")
        cards.append(
            f'<div class="hit-card" data-order="{order}"{meta} '
            f'style="left:{left}px;width:{w}px;z-index:{z};transform:rotate({rot}deg)">'
            f'<div class="hd"><span class="r">{_html.escape(r_label)}</span>'
            f'<span class="d">{_html.escape(str(date))}</span></div>'
            f'<div class="t">{_html.escape(_no_hanging(text))}</div></div>'
        )
    return _page_html(_u(NEW_BG / "Hit_post.png"), _HIT_CSS, "\n".join(cards))


# ---------------------------------------------------------------------------
# 07/09 — WORD CLOUDS. Генерим ТОЛЬКО облако (прозрачный фон, слова в маске),
# затем кладём картинкой поверх фона + накладываем название канала.
# Слова/маска — через WordCloud напрямую (без matplotlib-обёртки старого кода).
# ---------------------------------------------------------------------------
def _oval_mask(w: int = 920, h: int = 1040, jagged: bool = True):
    """Овальная маска с рваными краями (как в visualization/wordclouds.py)."""
    import math
    import numpy as np
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    cx, cy, rx, ry = w // 2, h // 2, w // 2 - 20, h // 2 - 20
    if not jagged:
        d.ellipse([20, 20, w - 20, h - 20], fill=0)
    else:
        rng = random.Random(42)
        pts = []
        for i in range(80):
            a = 2 * math.pi * i / 80
            n = rng.uniform(-0.15, 0.15)
            pts.append((int(cx + rx * (1 + n) * math.cos(a)),
                        int(cy + ry * (1 + n) * math.sin(a))))
        d.polygon(pts, fill=0)
    return np.array(img)


def gen_wordcloud_png(freqs: dict, out_path: str | Path, color: str = "#ffffff",
                      colors: list[str] | None = None, jagged: bool = True) -> Path:
    """Прозрачный PNG облака: белые (или из палитры) слова шрифтом Inter в овале."""
    from wordcloud import WordCloud

    def cf(*a, **k):
        return random.choice(colors) if colors else color

    wc = WordCloud(
        background_color=None, mode="RGBA", color_func=cf,
        mask=_oval_mask(jagged=jagged), max_words=200, min_font_size=8,
        prefer_horizontal=0.85, relative_scaling=0.5, random_state=42,
        font_path=str(FONTS / "Inter-Variable.ttf"),
    ).generate_from_frequencies(freqs)
    wc.to_image().save(str(out_path))
    return Path(out_path)


_CLOUD_CSS = """
  .cl-name{position:absolute;top:300px;left:0;width:1080px;text-align:center;
    font-weight:400;font-size:50px;color:#e6e6ec;}
  /* облако занимает y 454..1585 (высота 1131px), центрировано по горизонтали */
  .cl-img{position:absolute;top:454px;left:50%;transform:translateX(-50%);
    height:1131px;width:auto;}
"""


def word_cloud_html(channel_name: str, cloud_png: str | Path, bg_file: str) -> str:
    body = (
        f'<div class="cl-name">{_html.escape(str(channel_name))}</div>\n'
        f'<img class="cl-img" src="{_u(Path(cloud_png))}">'
    )
    return _page_html(_u(NEW_BG / bg_file), _CLOUD_CSS, body)


# ---------------------------------------------------------------------------
# 08 — POST BY DAYS  (фон: заголовок + пустая панель + плашка впечатаны)
# столбчатый график на HTML/CSS внутри панели.
# ---------------------------------------------------------------------------
# Точная геометрия из Figma 386:1291 (фон new_bg, панель+заголовок впечатаны):
# baseline(0)=y1405, верх(max)=y808, столбцы x249..849 шаг100 шир55, сетка x230..917,
# подписи дней @y1423, оси Y справа @x≈211, «Любимый день»@y623.
_PBD_BASE_Y = 1405
_PBD_TOP_Y = 808
_PBD_BAR_X = [249, 349, 449, 549, 649, 749, 849]
_PBD_BAR_W = 55
_PBD_GRID_L = 230
_PBD_GRID_W = 687
_PBD_CSS = """
  .pbd-head{position:absolute;top:623px;left:129px;width:823px;height:133px;
    display:flex;align-items:center;justify-content:center;
    font-weight:600;font-size:58px;color:#fff;white-space:nowrap;}
  .pbd-gl{position:absolute;left:230px;width:687px;height:1.7px;
    background:rgba(255,255,255,0.22);}
  .pbd-yl{position:absolute;width:60px;text-align:right;font-size:30px;
    color:#e2e2ec;transform:translateY(-50%);}
  /* столбик — матовое стекло (Figma): белый градиент 0.2→0.49, обводка #fff→прозр,
     backdrop-blur, скругление верха 20px (фон просвечивает = розовый оттенок) */
  .pbd-bar{position:absolute;width:55px;border-radius:20px 20px 0 0;
    background:linear-gradient(180deg,rgba(255,255,255,0.2),rgba(255,255,255,0.49));
    backdrop-filter:blur(30px);-webkit-backdrop-filter:blur(30px);
    border:1.5px solid rgba(255,255,255,0.35);border-bottom:none;
    border-top:2px solid rgba(255,255,255,0.85);
    box-shadow:inset 0 1px 6px rgba(255,255,255,0.35);}
  .pbd-val{position:absolute;width:55px;text-align:center;font-size:30px;
    font-weight:700;color:#fff;}
  .pbd-day{position:absolute;width:55px;text-align:center;font-size:30px;
    font-weight:800;color:#fff;}
"""


def _pbd_scale(raw_max: int) -> tuple[int, int]:
    """(шаг, кол-во интервалов) оси Y: минимальный «красивый» шаг, чтобы
    интервалов было ≤6, и верх оси прижат к максимуму (без пустых 50%+ сверху).
    Примеры: 59→(10,6)=60 (как Figma); 140→(25,6)=150; 192→(50,4)=200."""
    import math
    raw_max = max(1, raw_max)
    for s in (1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000, 2000):
        n = math.ceil(raw_max / s)
        if n <= 6:
            return s, max(n, 1)
    return 5000, max(math.ceil(raw_max / 5000), 1)


def post_by_days_html(counts: dict, favorite_day: str = "") -> str:
    days = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"]
    vals = [int(counts.get(i, 0)) for i in range(7)]
    step, n_int = _pbd_scale(max(vals) or 1)
    top_val = step * n_int
    span = _PBD_BASE_Y - _PBD_TOP_Y

    def y_of(v):  # y-координата для значения v
        return _PBD_BASE_Y - v / top_val * span

    # сетка + подписи оси Y (0..top_val)
    parts = []
    for k in range(n_int + 1):
        v = k * step
        y = y_of(v)
        parts.append(f'<div class="pbd-gl" style="top:{y:.1f}px"></div>')
        parts.append(f'<div class="pbd-yl" style="top:{y:.1f}px;left:{_PBD_GRID_L-72}px">{v}</div>')
    # столбцы + значения + подписи дней
    for x, d, v in zip(_PBD_BAR_X, days, vals):
        bar_top = y_of(v)
        h = _PBD_BASE_Y - bar_top
        parts.append(f'<div class="pbd-bar" style="left:{x}px;top:{bar_top:.1f}px;height:{h:.1f}px"></div>')
        parts.append(f'<div class="pbd-val" style="left:{x}px;top:{bar_top-46:.1f}px">{v}</div>')
        parts.append(f'<div class="pbd-day" style="left:{x}px;top:1423px">{d}</div>')
    # не шире сетки графика (687px), длинные дни ужимаются автофитом
    head = (f'<div class="pbd-head" data-fit data-fit-max="687">'
            f'<span class="fit">Любимый день – {_html.escape(str(favorite_day))}</span></div>')
    return _page_html(_u(NEW_BG / "post_by_days_weeks.png"), _PBD_CSS, head + "\n" + "\n".join(parts))


# ---------------------------------------------------------------------------
# BEST / recap — «X постов за всё время» (фон new_bg/1306010585.png)
# Координаты слотов взяты из Figma (фрейм 386:1113) через figma_extract.py.
# Статика («постов за всё время», бейдж, @insight_tg_bot) уже впечатана в фон —
# поверх кладём только динамику: заголовок, период, большое число, темп.
# ---------------------------------------------------------------------------
_BEST_CSS = """
  .b-title{position:absolute;left:75px;top:199px;width:950px;text-align:center;
    font-weight:700;font-size:100px;line-height:110px;letter-spacing:-4px;
    color:#fff;text-transform:uppercase;}
  .b-period{position:absolute;left:166px;top:538px;width:748px;text-align:center;
    font-weight:400;font-size:80px;line-height:104px;font-style:italic;color:#fff;}
  .b-big{position:absolute;left:55px;top:582px;width:970px;height:639px;
    display:flex;align-items:center;justify-content:center;
    font-family:'NooksScript';font-weight:700;font-size:450px;line-height:639px;
    letter-spacing:-18px;color:#fff7ff;}
  .b-rate{position:absolute;left:3px;top:1352px;width:1077px;text-align:center;
    font-weight:500;font-size:50px;line-height:66px;letter-spacing:-3.67px;color:#fbfbfb;}
"""


def best_html(channel_name: str, value: str, period: str, rate: str) -> str:
    """Карточка «итоги канала»: большое число постов на фоне 1306010585.

    channel_name — имя канала (каждое слово встаёт на свою строку под «TELEGRAM RECAP»);
    value — уже отформатированное число (напр. "18,5К"); period — "2017-2026";
    rate — подпись темпа (напр. "по ~5 в день · каждый день").
    """
    name_lines = "<br>".join(_html.escape(w) for w in str(channel_name).split())
    body = (
        f'<div class="b-title">Telegram Recap<br>{name_lines}</div>\n'
        f'<div class="b-period">{_html.escape(str(period))}</div>\n'
        f'<div class="b-big">{_html.escape(str(value))}</div>\n'
        f'<div class="b-rate">{_html.escape(str(rate))}</div>'
    )
    return _page_html(_u(NEW_BG / "1306010585.png"), _BEST_CSS, body)


# ---------------------------------------------------------------------------
# Рендер
# ---------------------------------------------------------------------------
def render_html(page_html: str, out_path: str | Path) -> Path:
    # HTML пишем во временный файл в проекте — чтобы Chromium грузил фон/шрифты
    # по file:// (из about:blank через set_content это блокируется политикой origin).
    import os
    import tempfile

    out_path = Path(out_path)
    fd, tmp = tempfile.mkstemp(suffix=".html", dir=str(ROOT / "cards_html"))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(page_html)
        with sync_playwright() as p:
            b = p.chromium.launch()
            page = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
            page.goto(Path(tmp).as_uri())
            try:
                page.wait_for_selector("body[data-ready='1']", timeout=3000)
            except Exception:
                page.wait_for_timeout(400)  # фолбэк если автофита нет
            page.screenshot(path=str(out_path), clip={"x": 0, "y": 0, "width": W, "height": H})
            b.close()
    finally:
        os.unlink(tmp)
    return out_path


def cmp_with_ref(rendered: str | Path, ref_jpg: str | Path, out: str | Path) -> Path:
    """Собрать сравнение: рендер | эталон (для цикла подгона)."""
    from PIL import Image
    r = Image.open(rendered).convert("RGB")
    e = Image.open(ref_jpg).convert("RGB").resize((W, H))
    c = Image.new("RGB", (W * 2, H))
    c.paste(r, (0, 0)); c.paste(e, (W, 0))
    c.save(out)
    return Path(out)


if __name__ == "__main__":
    # тест на эталонных данных + на других данных
    OUT = Path(__file__).parent / "out"
    OUT.mkdir(exist_ok=True)

    ref_data = ([("тбилиси", 66), ("петербург", 65), ("москва", 34),
                 ("берлин", 2), ("стамбул", 2), ("ереван", 1)], 195, "тбилиси")
    render_html(geography_html(*ref_data), OUT / "geography_data_ref.png")
    print("ref ->", OUT / "geography_data_ref.png")

    alt_data = ([("нью-йорк", 1204), ("лос-анджелес", 318), ("чикаго", 87),
                 ("майами", 40), ("бостон", 12), ("сиэтл", 3)], 1664, "нью-йорк")
    render_html(geography_html(*alt_data), OUT / "geography_data_alt.png")
    print("alt ->", OUT / "geography_data_alt.png")

    # best / recap — эталон (как в Figma) + другие данные
    render_html(best_html("новый положняк", "18,5К", "2017-2026",
                          "по ~5 в день · каждый день"), OUT / "best_data_ref.png")
    print("best ref ->", OUT / "best_data_ref.png")
    render_html(best_html("дайджест", "1,2К", "2020-2026",
                          "по ~2 в день · почти каждый день"), OUT / "best_data_alt.png")
    print("best alt ->", OUT / "best_data_alt.png")
