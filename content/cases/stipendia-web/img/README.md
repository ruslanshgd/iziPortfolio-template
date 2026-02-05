# Структура изображений для кейса

Все изображения кейса хранятся в папке `img/` с подпапками по блокам:

```
img/
├── cover/          # Обложка кейса (варианты A и B)
├── card/           # Картинка для карточки на главной странице
├── process/        # Изображения для блока "Процесс"
├── research/       # Изображения для блока "Исследование и контекст"
└── layouts/        # Изображения для блока "Макеты"
```

## Использование в front matter

### Обложка
- `cover_icon: "img/cover/icon.png"` (вариант A - иконка)
- `cover_image: "img/cover/hero.jpg"` (вариант B - картинка с оверлеем)

### Карточка на главной
- `card_image: "img/card/card.jpg"`

### Процесс
- `process_image: "img/process/process-diagram.png"`

### Исследование
```yaml
research_blocks:
  - title: "CJM"
    text: "Описание..."
    image: "img/research/cjm.png"
  - title: "Интервью"
    text: "Описание..."
    image: "img/research/interview-1.jpg"
```

### Макеты
```yaml
layout_blocks:
  - title: "Экран оценок"
    subtitle: "Описание"
    text: "Текст..."
    images: ["img/layouts/screen-1.png", "img/layouts/screen-2.png"]
```

## Для Telegram-бота

При сохранении изображений из Telegram:
- Обложка → `img/cover/`
- Карточка главной → `img/card/`
- Процесс → `img/process/`
- Исследование → `img/research/`
- Макеты → `img/layouts/`

В front matter указывать относительный путь от корня папки кейса (например, `"img/cover/hero.jpg"`).
