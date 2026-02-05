---
title: "{{ replace .File.ContentBaseName "-" " " | title }}"
date: {{ .Date }}
draft: false
type: "case"

# 1. Обложка: variant = "icon" | "image"
cover_variant: "icon"
cover_icon: ""           # путь к иконке (для variant icon), напр. "img/cover/icon" или "img/cover/icon.png" (поддержка: jpg, jpeg, png, webp)
cover_image: ""         # путь к картинке (для variant image), напр. "img/cover/hero" или "img/cover/hero.jpg" (поддержка: jpg, jpeg, png, webp)
cover_title: ""
cover_subtitle: ""      # 1-2 предложения о чём кейс
cover_meta: ""          # опционально, напр. "UX/UI Case study | 2021"
company_name: ""        # название компании для карточки на главной (32px bold)
card_image: ""          # опционально: картинка для карточки на главной (если не задано — используется cover_image), напр. "img/card/card" или "img/card/card.png" (поддержка: jpg, jpeg, png, webp)
platform: "web"         # "web" или "mobile" - определяет отступы и layout
layout: "center"        # "pinned" (правый нижний угол), "center" (центр справа), "bottom" (снизу справа)

# 2. О компании / продукте (1-4 строки, списком ок)
company:
  - ""

# 3. Целевая аудитория (1-2 строки)
audience: ""

# 4. Проблемы (1-4 строки, список)
problems:
  - ""

# 5. Роль (обязательно), команда (опционально)
role: ""
team: ""

# 6. Процесс
process_image: ""       # напр. "img/process/process-diagram" или "img/process/process-diagram.png" (поддержка: jpg, jpeg, png, webp)
process_text: ""

# 7. Исследование и контекст
research_context: ""
research_artifact: ""   # напр. CJM, зачем и результаты
research_blocks: []     # массив: { title, text, image }, напр. [{ title: "CJM", text: "...", image: "img/research/cjm" }] (поддержка: jpg, jpeg, png, webp)
insights: []            # обязательный список выводов/инсайтов

# 8. Макеты (повторяемый блок: заголовок, подзаголовок, текст, картинки)
layout_blocks: []
# - title: ""
#   subtitle: ""
#   text: ""
#   images: ["img/layouts/screen-1", "img/layouts/screen-2"]  # или с расширением: ["img/layouts/screen-1.png"] (поддержка: jpg, jpeg, png, webp)
# before_after: { before: "", after: "", metric: "" }  # опционально

# 9. Результаты кейса
results: ""
# или results_list: []
---
