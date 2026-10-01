"""Русские тексты бота. Разметка — HTML (parse_mode=HTML)."""

TEXTS: dict[str, str] = {
    # ---------- Общие ----------
    "common.back": "⬅️ Назад",
    "common.menu": "🏠 Главное меню",
    "common.cancel": "✖️ Отмена",
    "common.skip": "Пропустить",
    "common.done": "✅ Готово",
    "common.yes": "✅ Да",
    "common.no": "❌ Нет",
    "common.cancelled": "Действие отменено.",
    "common.error": "😔 Что-то пошло не так. Мы уже разбираемся — попробуйте ещё раз чуть позже.",
    "common.throttled": "Не так быстро 🙂",
    "common.not_found": "Не найдено.",
    "common.saved": "✅ Сохранено.",
    "common.deleted": "🗑 Удалено.",
    "common.unknown": "Я не понял сообщение. Нажмите кнопку в меню 👇",
    "common.prev": "◀️",
    "common.next": "▶️",
    "common.page": "{page}/{pages}",
    # ---------- Старт и меню ----------
    "start.welcome": (
        "👋 Привет, <b>{name}</b>!\n\n"
        "Добро пожаловать в <b>{shop}</b> — одежда и обувь с доставкой по всей России.\n"
        "Выбирайте в каталоге, спрашивайте ИИ-стилиста и оформляйте заказ прямо здесь."
    ),
    "start.my_id": "Ваш Telegram ID: <code>{user_id}</code>",
    "start.referral_joined": "🎁 Вы пришли по приглашению друга — после первого заказа он получит бонус.",
    "menu.title": "Главное меню 👇",
    "menu.catalog": "🛍 Каталог",
    "menu.search": "🔍 Поиск",
    "menu.cart": "🛒 Корзина",
    "menu.cart_count": "🛒 Корзина ({count})",
    "menu.orders": "📦 Мои заказы",
    "menu.favorites": "❤️ Избранное",
    "menu.stylist": "👗 ИИ-стилист",
    "menu.for_you": "✨ Подборка для вас",
    "menu.referral": "🎁 Пригласить друга",
    "menu.help": "💬 Помощь",
    "menu.admin": "⚙️ Админ-панель",
    # ---------- Справочники ----------
    "status.new": "🆕 Новый",
    "status.paid": "💳 Оплачен",
    "status.assembling": "📦 Собирается",
    "status.shipped": "🚚 Передан в доставку",
    "status.in_transit": "🛣 В пути",
    "status.delivered": "✅ Доставлен",
    "status.cancelled": "❌ Отменён",
    "status.returned": "↩️ Возврат",
    "delivery.courier": "🚴 Курьер",
    "delivery.cdek": "📦 СДЭК",
    "delivery.post": "✉️ Почта России",
    "delivery.pickup": "🏬 Самовывоз",
    "delivery.days_one": "{days} дн.",
    "delivery.days_range": "{dmin}–{dmax} дн.",
    "payment.card": "💳 Картой онлайн",
    "payment.cod": "💵 При получении",
    "gender.male": "Мужское",
    "gender.female": "Женское",
    "gender.unisex": "Унисекс",
    "style.casual": "Повседневный",
    "style.street": "Стритвир",
    "style.sport": "Спортивный",
    "style.classic": "Классика",
    "sort.new": "Новинки",
    "sort.cheap": "Сначала дешевле",
    "sort.expensive": "Сначала дороже",
    "sort.discount": "Со скидкой",
    "price.p1": "до 2 000 ₽",
    "price.p2": "2 000–5 000 ₽",
    "price.p3": "5 000–10 000 ₽",
    "price.p4": "от 10 000 ₽",
    # ---------- Каталог ----------
    "catalog.title": "🛍 <b>Каталог</b>\nВыберите категорию:",
    "catalog.empty_categories": "Каталог пока пуст. Загляните чуть позже!",
    "catalog.list_title": "<b>{category}</b>\nНайдено товаров: {count}{filters}",
    "catalog.filters_active": "\nФильтры: {filters}",
    "catalog.empty": "По выбранным фильтрам ничего не нашлось. Попробуйте сбросить фильтры.",
    "catalog.btn_filters": "⚙️ Фильтры",
    "catalog.btn_sort": "↕️ {sort}",
    "catalog.btn_categories": "⬅️ Категории",
    "catalog.filters_title": (
        "⚙️ <b>Фильтры</b>\n\n"
        "Размер: <b>{size}</b>\nЦвет: <b>{color}</b>\nЦена: <b>{price}</b>\nПол: <b>{gender}</b>\n\n"
        "Выберите параметр:"
    ),
    "catalog.any": "любой",
    "catalog.btn_size": "📏 Размер",
    "catalog.btn_color": "🎨 Цвет",
    "catalog.btn_price": "💰 Цена",
    "catalog.btn_gender": "🚻 Пол",
    "catalog.btn_reset": "♻️ Сбросить",
    "catalog.btn_show": "👀 Показать товары",
    "catalog.choose_value": "Выберите значение:",
    "catalog.sort_title": "↕️ Сортировка:",
    "catalog.product_btn": "{title} — {price}",
    "catalog.product_btn_sale": "🔥 {title} — {price}",
    # ---------- Карточка ----------
    "product.card": (
        "<b>{title}</b>\n"
        "{price}\n\n"
        "{description}\n\n"
        "🧵 <b>Состав:</b> {composition}\n"
        "🚻 {gender} · {style}\n"
        "🎨 Цвета: {colors}\n"
        "📦 {stock}"
    ),
    "product.in_stock": "В наличии: {count} шт.",
    "product.low_stock": "Осталось мало: {count} шт.",
    "product.out_of_stock": "Нет в наличии",
    "product.selected": "\n\n✅ Выбрано: <b>{size} · {color}</b> (осталось {stock} шт.)",
    "product.choose_color": "\n\n👇 Выберите цвет и размер",
    "product.choose_size": "\n\n👇 Выберите размер",
    "product.size_btn": "{size} ({stock})",
    "product.size_btn_none": "{size} ✖️",
    "product.btn_size_chart": "📏 Таблица размеров",
    "product.btn_to_cart": "🛒 В корзину",
    "product.btn_fav_add": "🤍 В избранное",
    "product.btn_fav_remove": "❤️ В избранном",
    "product.btn_similar": "🧩 Похожие",
    "product.btn_bought_with": "🛍 С этим покупают",
    "product.btn_back": "⬅️ К списку",
    "product.need_variant": "Сначала выберите размер 👆",
    "product.added": "✅ Добавлено в корзину: {title} ({size} · {color})",
    "product.not_enough": "😔 Столько нет на складе. Доступно: {stock} шт.",
    "product.unavailable": "Товар больше недоступен.",
    "product.fav_added": "❤️ Добавлено в избранное. Сообщим о скидке или поступлении.",
    "product.fav_removed": "Убрано из избранного.",
    "product.similar_title": "🧩 <b>Похожие товары</b>",
    "product.bought_with_title": "🛍 <b>С этим покупают</b>",
    "product.no_recommendations": "Пока нечего предложить — загляните в каталог.",
    "product.size_chart": (
        "📏 <b>Таблица размеров (одежда)</b>\n"
        "<pre>"
        "Размер  Грудь   Талия   Бёдра\n"
        "XS      82–86   66–70   88–92\n"
        "S       86–90   70–74   92–96\n"
        "M       90–96   74–80   96–102\n"
        "L       96–102  80–86   102–108\n"
        "XL      102–108 86–94   108–114\n"
        "XXL     108–116 94–102  114–120"
        "</pre>\n"
        "👟 <b>Обувь</b>: размер RU = длина стопы (см) × 1,5 + 1,5\n"
        "<pre>"
        "RU 39 — 25,0 см   RU 42 — 27,0 см\n"
        "RU 40 — 25,7 см   RU 43 — 27,7 см\n"
        "RU 41 — 26,3 см   RU 44 — 28,3 см"
        "</pre>"
    ),
    # ---------- Поиск ----------
    "search.prompt": "🔍 Введите название товара (например: <i>худи</i> или <i>джинсы</i>):",
    "search.too_short": "Введите хотя бы 2 символа.",
    "search.results": "🔍 Результаты по запросу «{query}»: {count}",
    "search.empty": "По запросу «{query}» ничего не нашлось. Попробуйте другое слово.",
    # ---------- Избранное ----------
    "fav.title": "❤️ <b>Избранное</b>",
    "fav.empty": "В избранном пока пусто. Нажимайте 🤍 на карточках товаров.",
    "fav.price_drop": (
        "🔥 Товар из избранного подешевел!\n<b>{title}</b>: <s>{old}</s> → <b>{new}</b>"
    ),
    "fav.back_in_stock": "📦 Товар из избранного снова в наличии!\n<b>{title}</b> — {price}",
    "fav.open": "👀 Посмотреть",
    # ---------- Корзина ----------
    "cart.title": "🛒 <b>Корзина</b>\n",
    "cart.empty": "🛒 Корзина пуста. Загляните в каталог!",
    "cart.line": "{n}. {title} ({size} · {color})\n    {qty} × {price} = <b>{subtotal}</b>",
    "cart.line_short": "{n}. {title} ({size}) ⚠️ осталось {stock} шт.",
    "cart.items_total": "\nТовары: {total}",
    "cart.discount": "Скидка по промокоду {code}: −{discount}",
    "cart.total": "<b>Итого: {total}</b>",
    "cart.promo_invalid": "⚠️ Промокод {code} больше не действует: {reason}",
    "cart.btn_promo": "🏷 Промокод",
    "cart.btn_remove_promo": "✖️ Убрать промокод",
    "cart.btn_clear": "🗑 Очистить",
    "cart.btn_checkout": "✅ Оформить заказ",
    "cart.cleared": "Корзина очищена.",
    "cart.item_removed": "Товар удалён из корзины.",
    "cart.max_reached": "Больше нет на складе.",
    "cart.enter_promo": "🏷 Введите промокод:",
    "cart.promo_applied": "✅ Промокод {code} применён: скидка {discount}.",
    "cart.promo_removed": "Промокод убран.",
    "cart.reminder": (
        "👋 Вы оставили товары в корзине — они всё ещё ждут вас!\n"
        "{items}\n\nОформить заказ можно в пару касаний 👇"
    ),
    "cart.reminder_btn": "🛒 Открыть корзину",
    "cart.stock_problem": "⚠️ Некоторых товаров больше нет в нужном количестве — проверьте корзину.",
    # ---------- Промокоды: причины отказа ----------
    "promo.not_found": "промокод не найден",
    "promo.inactive": "промокод отключён",
    "promo.not_started": "промокод ещё не начал действовать",
    "promo.expired": "срок действия истёк",
    "promo.exhausted": "лимит использований исчерпан",
    "promo.user_limit": "вы уже использовали этот промокод",
    "promo.min_total": "минимальная сумма заказа — {min_total}",
    # ---------- Оформление ----------
    "checkout.consent": (
        "📄 <b>Согласие на обработку персональных данных</b>\n\n"
        "Для оформления заказа нам нужны ваши имя, телефон и адрес доставки. "
        "Мы используем их только для выполнения заказа и связи с вами, передаём лишь службе "
        "доставки и не храним дольше, чем требует закон (152-ФЗ «О персональных данных»).\n\n"
        "Политика конфиденциальности: {url}\n\n"
        "Нажимая «Согласен», вы даёте согласие на обработку персональных данных."
    ),
    "checkout.btn_agree": "✅ Согласен",
    "checkout.btn_decline": "❌ Не согласен",
    "checkout.declined": "Без согласия на обработку данных оформить заказ нельзя. Корзина сохранена.",
    "checkout.ask_name": "👤 Как к вам обращаться? Введите имя и фамилию получателя:",
    "checkout.bad_name": "Имя должно содержать от 2 до 64 букв. Попробуйте ещё раз:",
    "checkout.ask_phone": "📱 Отправьте номер телефона кнопкой ниже или введите вручную (+7…):",
    "checkout.btn_contact": "📱 Отправить контакт",
    "checkout.bad_phone": "Не похоже на российский номер. Пример: +7 912 345-67-89",
    "checkout.foreign_contact": "Пожалуйста, отправьте свой контакт или введите номер вручную.",
    "checkout.ask_method": "🚚 Выберите способ доставки:",
    "checkout.ask_city": "🏙 Введите город доставки:",
    "checkout.bad_city": "Название города выглядит странно. Введите, например: Москва",
    "checkout.ask_address": (
        "📍 Введите адрес: улица, дом, квартира (для СДЭК и Почты — можно адрес пункта выдачи, "
        "для Почты добавьте индекс):"
    ),
    "checkout.bad_address": (
        "Адрес слишком короткий или без номера дома. Пример: ул. Ленина, д. 5, кв. 12"
    ),
    "checkout.pickup_info": "🏬 Самовывоз: {address}",
    "checkout.no_tariff": "😔 Этот способ доставки недоступен для города {city}. Выберите другой:",
    "checkout.summary": (
        "🧾 <b>Проверьте заказ</b>\n\n"
        "{items}\n\n"
        "👤 {name}, {phone}\n"
        "🚚 {method}: {address}\n"
        "⏱ Срок доставки: {days}\n\n"
        "Товары: {items_total}\n"
        "{discount_line}"
        "{bonus_line}"
        "Доставка: {delivery}\n"
        "<b>К оплате: {total}</b>"
    ),
    "checkout.discount_line": "Скидка: −{discount}\n",
    "checkout.bonus_line": "Бонусы: −{bonus}\n",
    "checkout.free": "бесплатно",
    "checkout.btn_confirm": "✅ Подтвердить",
    "checkout.btn_use_bonus": "🎁 Списать бонусы (до {amount})",
    "checkout.btn_drop_bonus": "↩️ Не списывать бонусы",
    "checkout.btn_edit": "✏️ Изменить данные",
    "checkout.ask_payment": "💳 Выберите способ оплаты:",
    "checkout.btn_pay_test": "💳 Оплатить (тестовый режим)",
    "checkout.cart_changed": "⚠️ Корзина изменилась или товара не хватает на складе. Проверьте корзину.",
    "checkout.created_cod": (
        "🎉 Заказ <b>№{order_id}</b> оформлен! Оплата при получении — {total}.\n"
        "Мы пришлём уведомление, когда заказ будет собран и отправлен."
    ),
    "checkout.created_card": "🧾 Заказ <b>№{order_id}</b> создан. Оплатите его, чтобы мы начали сборку:",
    "checkout.invoice_title": "Заказ №{order_id}",
    "checkout.invoice_description": "Оплата заказа №{order_id} в {shop}",
    "checkout.invoice_items": "Товары",
    "checkout.invoice_delivery": "Доставка",
    "checkout.test_mode_note": (
        "ℹ️ Включён тестовый режим оплаты: деньги не списываются, заказ просто отметится оплаченным."
    ),
    "checkout.paid": "✅ Оплата получена! Заказ <b>№{order_id}</b> передан в работу.",
    "checkout.payment_failed": "😔 Не удалось провести оплату заказа. Попробуйте ещё раз.",
    "checkout.payment_not_available": "Онлайн-оплата временно недоступна. Выберите оплату при получении.",
    "checkout.pre_checkout_error": "Заказ изменился или товара не хватает. Оформите заказ заново.",
    # ---------- Заказы ----------
    "orders.title": "📦 <b>Мои заказы</b>",
    "orders.empty": "У вас пока нет заказов.",
    "orders.btn": "№{id} · {status} · {total}",
    "orders.card": (
        "📦 <b>Заказ №{id}</b> от {date}\n"
        "Статус: <b>{status}</b>\n\n"
        "{items}\n\n"
        "🚚 {method}: {address}\n"
        "💳 {payment}{paid}\n"
        "{track}"
        "Товары: {items_total}\n"
        "{discount_line}"
        "{bonus_line}"
        "Доставка: {delivery}\n"
        "<b>Итого: {total}</b>\n\n"
        "<b>История:</b>\n{history}"
    ),
    "orders.paid_mark": " ✅ оплачен",
    "orders.unpaid_mark": " ⏳ не оплачен",
    "orders.track": "🔎 Трек-номер: <code>{track}</code>\n",
    "orders.btn_repeat": "🔁 Повторить заказ",
    "orders.btn_cancel": "❌ Отменить заказ",
    "orders.btn_pay": "💳 Оплатить",
    "orders.btn_track": "🔎 Где посылка?",
    "orders.repeat_done": "🛒 Добавлено в корзину: {added} поз.{missing}",
    "orders.repeat_missing": "\nНет в наличии: {items}",
    "orders.cancel_confirm": "Отменить заказ №{id}?",
    "orders.cancelled_by_user": "Заказ №{id} отменён.",
    "orders.cancel_refund_note": "Деньги вернутся на карту в течение 3–10 рабочих дней.",
    "orders.cannot_cancel": "Этот заказ уже нельзя отменить — напишите менеджеру.",
    "orders.status_changed": "📦 Заказ <b>№{id}</b>: статус изменён на <b>{status}</b>.{extra}",
    "orders.status_track_extra": "\nТрек-номер: <code>{track}</code>",
    "orders.tracking": "🔎 <b>Отслеживание {track}</b>\n{events}",
    "orders.tracking_unavailable": "Информация об отслеживании пока недоступна.",
    "orders.auto_cancelled": "Заказ №{id} отменён: он не был оплачен в течение {hours} ч.",
    # ---------- Рекомендации / рефералы ----------
    "recs.for_you": "✨ <b>Подборка для вас</b>\nНа основе ваших просмотров и покупок:",
    "recs.popular": "✨ <b>Популярное сейчас</b>",
    "ref.info": (
        "🎁 <b>Приглашайте друзей</b>\n\n"
        "Отправьте другу ссылку. Когда он сделает первый заказ, вы получите "
        "<b>{bonus}</b> бонусами. Бонусами можно оплатить до {share}% следующих заказов.\n\n"
        "Ваша ссылка:\n<code>{link}</code>\n\n"
        "Приглашено: {invited} · Бонусный баланс: <b>{balance}</b>"
    ),
    "ref.rewarded": "🎉 Ваш друг сделал первый заказ! Начислено {bonus} бонусов.",
    # ---------- Помощь ----------
    "help.title": "💬 <b>Помощь</b>\nВыберите тему или напишите менеджеру:",
    "help.btn_delivery": "🚚 Доставка",
    "help.btn_returns": "↩️ Возврат и обмен",
    "help.btn_sizes": "📏 Как выбрать размер",
    "help.btn_payment": "💳 Оплата",
    "help.btn_manager": "✍️ Написать менеджеру",
    "help.delivery": (
        "🚚 <b>Доставка</b>\n\n"
        "• Курьер — Москва и Санкт-Петербург, 1–2 дня.\n"
        "• СДЭК — пункты выдачи и курьер по всей России, 2–7 дней.\n"
        "• Почта России — в любой населённый пункт, 5–14 дней.\n"
        "• Самовывоз из шоурума — бесплатно, на следующий день.\n\n"
        "Стоимость рассчитывается при оформлении в зависимости от города. "
        "После отправки вы получите трек-номер."
    ),
    "help.returns": (
        "↩️ <b>Возврат и обмен</b>\n\n"
        "Вернуть или обменять товар надлежащего качества можно в течение 14 дней, "
        "если сохранены бирки и товарный вид (ст. 25 Закона «О защите прав потребителей»).\n"
        "Напишите менеджеру номер заказа — пришлём инструкцию и адрес для возврата. "
        "Деньги возвращаются в течение 10 дней после получения товара."
    ),
    "help.sizes": "📏 <b>Как выбрать размер</b>\n\nСнимите мерки по таблице ниже. "
    "Если вы между размерами — берите больший, или спросите ИИ-стилиста.",
    "help.payment": (
        "💳 <b>Оплата</b>\n\n"
        "• Картой онлайн прямо в Telegram (платёжный сервис ЮKassa).\n"
        "• При получении — наличными или картой курьеру / в пункте выдачи.\n"
        "Чек приходит на почту или в Telegram."
    ),
    "help.ask_manager": (
        "✍️ Напишите вопрос одним сообщением (можно с фото) — менеджер ответит здесь же."
    ),
    "help.sent": "✅ Сообщение передано менеджеру. Ответ придёт в этот чат.",
    "help.manager_reply": "💬 <b>Ответ менеджера:</b>\n\n{text}",
    "help.no_admins": "Сейчас менеджеры недоступны. Попробуйте позже.",
    # ---------- ИИ-стилист ----------
    "stylist.intro": (
        "👗 <b>ИИ-стилист</b>\n\n"
        "Опишите, что ищете — повод, бюджет, размер, любимые цвета. Например:\n"
        "<i>«Нужен образ на свидание, бюджет 10 000, размер M, люблю тёмные цвета»</i>\n\n"
        "Или пришлите фото вещи/образа — найду похожее в нашем каталоге.\n"
        "Осталось запросов сегодня: {left}"
    ),
    "stylist.btn_pair": "🧩 Что надеть с…",
    "stylist.btn_capsule": "🧳 Капсульный гардероб",
    "stylist.btn_reset": "🔄 Начать заново",
    "stylist.btn_catalog": "🛍 Открыть каталог",
    "stylist.btn_look_to_cart": "🛒 Добавить весь образ в корзину",
    "stylist.btn_other": "🔄 Подобрать другое",
    "stylist.look": "✨ <b>{title}</b>\n{explanation}\n\n{items}\n\n<b>Сумма образа: {total}</b>",
    "stylist.look_item": "• {title}{size} — {price}",
    "stylist.disabled": "ИИ-стилист сейчас отключён. Загляните в каталог 👇",
    "stylist.limit": (
        "На сегодня лимит запросов к стилисту исчерпан ({limit}). Возвращайтесь завтра, "
        "а пока посмотрите каталог 👇"
    ),
    "stylist.unavailable": (
        "😔 Стилист сейчас недоступен. Пока он отдыхает, подобрать вещи можно в каталоге 👇"
    ),
    "stylist.reset_done": "🔄 Начнём сначала! Расскажите, что ищете.",
    "stylist.pair_choose": "🧩 К какой вещи подобрать образ?",
    "stylist.pair_empty": "В корзине и прошлых заказах пока нет вещей. Выберите товар в каталоге.",
    "stylist.pair_request": "Подбери образ, который хорошо сочетается с товаром #{pid} «{title}».",
    "stylist.capsule_prompt": (
        "🧳 Напишите сезон и бюджет капсулы, например: <i>«осень, 25 000, размер M, женское»</i>"
    ),
    "stylist.capsule_request": "Собери капсульный гардероб: {text}",
    "stylist.other_request": "Подбери другие варианты, не повторяя предыдущие товары.",
    "stylist.look_added": "✅ Образ добавлен в корзину: {count} поз.",
    "stylist.look_partial": "\nВыберите размер в карточке для: {items}",
    "stylist.look_missing": "😔 Этих вещей уже нет в наличии. Попробуйте подобрать другое.",
    "stylist.photo_caption_default": "Найди в каталоге похожие вещи и собери образ.",
    "stylist.refusal": "Я могу помочь только с подбором одежды и заказами 🙂 Расскажите, какой образ ищете?",
    "stylist.empty_answer": "Не удалось подобрать образ. Уточните запрос — повод, бюджет или размер.",
    "stylist.photo_too_big": "Фото слишком большое. Пришлите изображение поменьше.",
    # ---------- Уведомления админам ----------
    "admin.new_order": (
        "🆕 <b>Новый заказ №{id}</b>\n"
        "{customer}, {phone} (id <code>{user_id}</code>)\n"
        "🚚 {method}: {address}\n"
        "💳 {payment}\n\n{items}\n\n<b>Итого: {total}</b>"
    ),
    "admin.order_paid": "💳 Заказ №{id} оплачен ({total}).",
    "admin.refund_needed": "⚠️ Заказ №{id} отменён покупателем после оплаты — оформите возврат {total}.",
    "admin.support_message": "✉️ <b>Сообщение от покупателя</b> {name} (@{username}, id <code>{user_id}</code>)\n"
    "Ответьте реплаем на это сообщение — ответ уйдёт покупателю.",
    "admin.reply_sent": "✅ Ответ отправлен.",
    "admin.reply_failed": "Не удалось отправить ответ: пользователь заблокировал бота.",
    "admin.reply_unknown": "Не нашёл, кому ответить. Используйте /reply <id> <текст>.",
    # ---------- Админ-панель ----------
    "adm.title": "⚙️ <b>Админ-панель</b>",
    "adm.btn_products": "👕 Товары",
    "adm.btn_categories": "🗂 Категории",
    "adm.btn_promos": "🏷 Промокоды",
    "adm.btn_tariffs": "🚚 Тарифы доставки",
    "adm.btn_orders": "📦 Заказы",
    "adm.btn_stats": "📊 Статистика",
    "adm.btn_broadcast": "📣 Рассылка",
    "adm.btn_stylist": "👗 ИИ-стилист",
    "adm.no_access": "Нет доступа.",
    "adm.no_access_id": (
        "Админ-панель доступна только администраторам магазина.\n"
        "Ваш ID: <code>{user_id}</code> — передайте его владельцу, чтобы он добавил вас "
        "в разделе «👥 Админы»."
    ),
    "adm.claimed": (
        "👑 Вы — владелец магазина! Админ-панель открыта.\n\n"
        "Сюда будут приходить новые заказы и сообщения покупателей. "
        "Других администраторов добавьте в разделе «👥 Админы»."
    ),
    "adm.btn_team": "👥 Админы",
    "adm.team_title": "👥 <b>Администраторы</b>\n{admins}\n\n🔒 — заданы в настройках хостинга (ADMIN_IDS), удалить их можно только там.",
    "adm.btn_add_admin": "➕ Добавить админа",
    "adm.add_admin_prompt": (
        "Нажмите «👤 Выбрать из контактов» внизу экрана, перешлите сюда любое сообщение "
        "будущего админа или отправьте его числовой ID (он может узнать его командой /myid)."
    ),
    "adm.btn_pick_user": "👤 Выбрать из контактов",
    "adm.admin_added": (
        "✅ Администратор <code>{user_id}</code> добавлен. Попросите его открыть бота и "
        "отправить /start — иначе Telegram не даст боту написать ему первым."
    ),
    "adm.admin_exists": "Этот пользователь уже администратор.",
    "adm.admin_removed": "Администратор удалён.",
    "adm.admin_cannot_remove": "Этого администратора удалить нельзя: он задан в ADMIN_IDS или он последний.",
    "adm.bad_admin": "Не удалось определить пользователя. Пришлите числовой ID или воспользуйтесь кнопкой.",
    "adm.confirm_remove_admin": "Удалить администратора <code>{user_id}</code>?",
    "adm.enter_value": "Введите новое значение:",
    "adm.bad_value": "Некорректное значение, попробуйте ещё раз.",
    "adm.products_title": "👕 <b>Товары</b> — выберите категорию:",
    "adm.products_in_cat": "👕 <b>{category}</b>: {count} товаров",
    "adm.btn_add_product": "➕ Добавить товар",
    "adm.product_card": (
        "<b>#{id} {title}</b> {active}\n"
        "Категория: {category}\n"
        "Цена: {price}{old_price}\n"
        "Пол: {gender} · Стиль: {style}\n"
        "Состав: {composition}\n"
        "Фото: {photos} шт.\n\n"
        "{description}\n\n"
        "<b>Остатки:</b>\n{variants}"
    ),
    "adm.active": "🟢",
    "adm.inactive": "🔴 скрыт",
    "adm.btn_edit_title": "✏️ Название",
    "adm.btn_edit_description": "✏️ Описание",
    "adm.btn_edit_composition": "✏️ Состав",
    "adm.btn_edit_price": "💰 Цена",
    "adm.btn_edit_old_price": "💸 Старая цена",
    "adm.btn_edit_photos": "🖼 Фото",
    "adm.btn_edit_variants": "📦 Размеры и остатки",
    "adm.btn_toggle": "👁 Скрыть/показать",
    "adm.btn_delete": "🗑 Удалить",
    "adm.confirm_delete": "Точно удалить «{title}»? Это действие необратимо.",
    "adm.add_choose_category": "Выберите категорию нового товара:",
    "adm.add_title": "Введите название товара:",
    "adm.add_description": "Введите описание:",
    "adm.add_composition": "Введите состав (например: 100% хлопок):",
    "adm.add_gender": "Выберите пол:",
    "adm.add_style": "Выберите стиль:",
    "adm.add_price": "Введите цену в рублях (целое число):",
    "adm.add_old_price": "Введите старую цену (для скидки) или «-», если её нет:",
    "adm.add_photos": "Пришлите фото товара (одно или несколько). Когда закончите — нажмите «Готово».",
    "adm.photo_saved": "Фото {n} сохранено.",
    "adm.add_variants": (
        "Введите размеры, цвета и остатки — по строке на вариант:\n"
        "<code>M чёрный 5\nL чёрный 3\nM белый 0</code>"
    ),
    "adm.bad_variants": "Не удалось разобрать строку: {line}. Формат: «размер цвет количество».",
    "adm.product_created": "✅ Товар #{id} создан.",
    "adm.variants_title": "📦 Варианты товара «{title}». Нажмите на вариант, чтобы изменить остаток:",
    "adm.btn_add_variants": "➕ Добавить варианты",
    "adm.enter_stock": "Введите новый остаток для {label}:",
    "adm.photos_title": "🖼 Фото: {count} шт. Пришлите новые фото — они заменят текущие. Затем «Готово».",
    "adm.photos_replaced": "✅ Фото обновлены ({count} шт.).",
    "adm.categories_title": "🗂 <b>Категории</b>",
    "adm.btn_add_category": "➕ Добавить категорию",
    "adm.enter_category": "Введите эмодзи и название через пробел, например: <code>🧢 Кепки</code>",
    "adm.category_card": "<b>{label}</b> {active}\nТоваров: {count}",
    "adm.btn_rename": "✏️ Переименовать",
    "adm.category_not_empty": "Нельзя удалить категорию с товарами.",
    "adm.promos_title": "🏷 <b>Промокоды</b>",
    "adm.btn_add_promo": "➕ Создать промокод",
    "adm.promo_line": "{code}: {value} · исп. {used}/{max} · до {to} {active}",
    "adm.promo_card": (
        "🏷 <b>{code}</b> {active}\nСкидка: {value}\nМин. сумма: {min_total}\n"
        "Действует: {valid_from} — {valid_to}\nИспользований: {used}/{max} (на пользователя: {per_user})"
    ),
    "adm.promo_code": "Введите код промокода (латиница/цифры, 3–32 символа):",
    "adm.promo_kind": "Тип скидки:",
    "adm.promo_percent": "Процент",
    "adm.promo_fixed": "Фиксированная сумма",
    "adm.promo_value": "Размер скидки (число: проценты 1–90 или рубли):",
    "adm.promo_min_total": "Минимальная сумма заказа в рублях (0 — без ограничения):",
    "adm.promo_valid_to": "Дата окончания в формате ДД.ММ.ГГГГ или «-» — бессрочно:",
    "adm.promo_max_uses": "Общий лимит использований (число) или «-» — без лимита:",
    "adm.promo_exists": "Такой промокод уже существует.",
    "adm.promo_created": "✅ Промокод {code} создан.",
    "adm.tariffs_title": "🚚 <b>Тарифы доставки</b>\nЗоны и тарифы — выберите зону:",
    "adm.zone_card": "<b>{name}</b>{default}\nГорода: {cities}\n\n{tariffs}",
    "adm.zone_default": " (по умолчанию для остальных городов)",
    "adm.tariff_line": "{method}: {price}{free} · {days}{active}",
    "adm.tariff_free": ", бесплатно от {free}",
    "adm.btn_add_zone": "➕ Добавить зону",
    "adm.btn_edit_cities": "✏️ Города",
    "adm.enter_zone": "Введите: <code>Название; город1, город2</code>",
    "adm.enter_cities": "Введите города через запятую:",
    "adm.enter_tariff": (
        "Введите параметры тарифа {method}: <code>цена бесплатно_от дней_мин дней_макс</code>\n"
        "Например: <code>350 5000 2 4</code> (бесплатно_от «-» — без бесплатной доставки, "
        "цена «off» — отключить способ)"
    ),
    "adm.orders_title": "📦 <b>Заказы</b> — фильтр по статусу:",
    "adm.orders_all": "Все",
    "adm.orders_list": "📦 Заказы ({filter}): {count}",
    "adm.order_card_extra": "\n👤 {customer}, {phone} (id <code>{user_id}</code>)",
    "adm.btn_set_track": "🔎 Ввести трек-номер",
    "adm.btn_create_shipment": "📮 Создать отправление",
    "adm.enter_track": "Введите трек-номер:",
    "adm.track_saved": "✅ Трек-номер сохранён и отправлен покупателю.",
    "adm.status_changed": "✅ Статус изменён: {status}",
    "adm.bad_transition": "Недопустимый переход статуса.",
    "adm.shipment_created": "✅ Отправление создано, трек-номер: {track}",
    "adm.stats_title": "📊 <b>Статистика</b> — выберите период:",
    "adm.period_day": "День",
    "adm.period_week": "Неделя",
    "adm.period_month": "Месяц",
    "adm.stats": (
        "📊 <b>Статистика за {period}</b>\n\n"
        "Новых пользователей: {new_users}\n"
        "Заказов: {orders} (оплачено/подтверждено: {success})\n"
        "Выручка: <b>{revenue}</b>\n"
        "Средний чек: {avg}\n"
        "Конверсия корзина → заказ: <b>{conversion}%</b> ({ordered} из {carted})\n\n"
        "<b>Топ товаров:</b>\n{top}\n\n"
        "<b>Источники трафика:</b>\n{sources}\n\n"
        "<b>Рефералы:</b> приглашено {referred}, с заказом {referred_buyers}"
    ),
    "adm.stylist_stats": (
        "👗 <b>ИИ-стилист</b>\n\n"
        "Модель: <code>{model}</code> · {enabled}\n\n"
        "Сегодня: {day_requests} запросов, {day_cost}\n"
        "За месяц: {month_requests} запросов, {month_cost}\n"
        "Ошибок за месяц: {month_errors}\n"
        "Токены за месяц: вход {in_tokens}, выход {out_tokens}, кэш {cache_tokens}\n\n"
        "Образов предложено: {looks}\n"
        "Добавлено в корзину: {looks_carted}\n"
        "Превратилось в заказ: {looks_ordered}"
    ),
    "adm.enabled": "🟢 включён",
    "adm.disabled": "🔴 выключен",
    "adm.bc_segment": "📣 <b>Рассылка</b>\nВыберите аудиторию:",
    "adm.bc_seg_all": "👥 Все",
    "adm.bc_seg_buyers": "💳 Покупатели",
    "adm.bc_seg_abandoned": "🛒 Брошенная корзина",
    "adm.bc_seg_category": "🗂 По интересу к категории",
    "adm.bc_category": "Выберите категорию интереса:",
    "adm.bc_text": "Отправьте текст рассылки (можно с фото — фото с подписью):",
    "adm.bc_product": "Укажите ID товара для кнопки «Посмотреть» или «-», если кнопка не нужна:",
    "adm.bc_preview": "👆 Так будет выглядеть сообщение. Получателей: {count}.",
    "adm.btn_bc_send": "🚀 Отправить сейчас",
    "adm.btn_bc_schedule": "⏰ Запланировать",
    "adm.bc_enter_time": "Введите дату и время отправки (МСК) в формате ДД.ММ.ГГГГ ЧЧ:ММ:",
    "adm.bc_scheduled": "⏰ Рассылка #{id} запланирована на {when}.",
    "adm.bc_started": "🚀 Рассылка #{id} запущена. Получателей: {count}.",
    "adm.bc_finished": "📣 Рассылка #{id} завершена: доставлено {sent}, ошибок {failed}.",
    "adm.bc_view_product": "👀 Посмотреть",
}
