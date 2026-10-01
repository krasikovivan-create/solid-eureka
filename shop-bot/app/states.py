from aiogram.fsm.state import State, StatesGroup


class SearchStates(StatesGroup):
    query = State()


class CartStates(StatesGroup):
    promo = State()


class CheckoutStates(StatesGroup):
    consent = State()
    name = State()
    phone = State()
    city = State()
    method = State()
    address = State()
    confirm = State()
    payment = State()


class SupportStates(StatesGroup):
    message = State()


class StylistStates(StatesGroup):
    chat = State()
    capsule = State()


class AdminProductStates(StatesGroup):
    title = State()
    description = State()
    composition = State()
    price = State()
    old_price = State()
    photos = State()
    variants = State()
    edit_field = State()
    edit_photos = State()
    edit_stock = State()
    add_variants = State()


class AdminCategoryStates(StatesGroup):
    create = State()
    rename = State()


class AdminPromoStates(StatesGroup):
    code = State()
    value = State()
    min_total = State()
    valid_to = State()
    max_uses = State()


class AdminZoneStates(StatesGroup):
    create = State()
    cities = State()
    tariff = State()


class AdminOrderStates(StatesGroup):
    track = State()


class AdminBroadcastStates(StatesGroup):
    content = State()
    product = State()
    schedule = State()


class AdminTeamStates(StatesGroup):
    add = State()
