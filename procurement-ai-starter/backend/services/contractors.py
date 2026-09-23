import re
from datetime import date
from decimal import Decimal

from backend.models.contractor import (
    ContractorCard,
    ContractorProfile,
    ContractorSearchRequest,
    ContractorSearchResult,
)
from backend.integrations.contractors import ContractorCatalogAdapter


_CALENDAR_START = date(2026, 9, 23)
_CALENDAR_END = date(2026, 12, 31)
_CATEGORY_ALIASES = {
    "ведущий": "host", "ведущая": "host", "host": "host", "emcee": "host",
    "фотограф": "photographer", "photographer": "photographer",
    "банкетный зал": "banquet hall", "банкет зал": "banquet hall", "banquet hall": "banquet hall",
    "флорист": "florist", "флористика": "florist", "florist": "florist",
    "декоратор": "decorator", "декоратор мероприятий": "decorator", "decorator": "decorator",
    "подарки и сувениры": "gifts and souvenirs", "сувениры": "gifts and souvenirs", "gifts and souvenirs": "gifts and souvenirs",
    "ведущий церемонии": "ceremony host", "ceremony host": "ceremony host",
    "фото и видеобудки": "photo booth", "фото-видеобудка": "photo booth", "photo booth": "photo booth",
    "отель": "hotel", "гостиница": "hotel", "hotel": "hotel",
    "инструменталист": "instrumentalist", "instrumentalist": "instrumentalist",
    "кейтеринг": "catering", "catering": "catering",
    "видеограф": "videographer", "videographer": "videographer",
    "техническое обеспечение": "event technology", "звук и свет": "event technology", "event technology": "event technology",
}
_CITY_ALIASES = {
    "алматы": "almaty", "almaty": "almaty", "астана": "astana", "нур-султан": "astana", "astana": "astana",
    "зарубежье": "abroad", "за рубежом": "abroad", "abroad": "abroad",
}
_FORMAT_ALIASES = {
    "свадьба": "wedding", "свадьбе": "wedding", "wedding": "wedding",
    "той": "toi", "тойға": "toi", "toi": "toi",
    "корпоратив": "corporate", "корпоратива": "corporate", "корпоративное мероприятие": "corporate", "corporate": "corporate",
    "конференция": "conference", "конференции": "conference", "conference": "conference",
    "юбилей": "anniversary", "anniversary": "anniversary",
    "день рождения": "birthday", "дня рождения": "birthday", "birthday": "birthday",
}
_LANGUAGE_ALIASES = {
    "русский": "ru", "русском": "ru", "russian": "ru", "ru": "ru",
    "казахский": "kk", "казахском": "kk", "қазақша": "kk", "kazakh": "kk", "kk": "kk",
    "английский": "en", "английском": "en", "english": "en", "en": "en",
}
_TOKEN_RE = re.compile(r"[a-zа-яёәіңғүұқөһ]+", re.IGNORECASE)
_STOP_WORDS = {"для", "и", "или", "на", "в", "с", "по", "the", "a", "an", "for", "and", "event"}


class ContractorMatchingService:
    def __init__(self, catalog: ContractorCatalogAdapter) -> None:
        self._catalog = catalog

    def search(self, request: ContractorSearchRequest) -> ContractorSearchResult:
        if not (_CALENDAR_START <= request.event_date <= _CALENDAR_END):
            raise ValueError(
                f"Availability calendar covers {_CALENDAR_START.isoformat()} through {_CALENDAR_END.isoformat()} only."
            )

        profiles = self._catalog.list_profiles()
        city_key = self._city_key(request.city)
        category_key = self._category_key(request.category)
        city_profiles = [p for p in profiles if self._city_key(p.city) == city_key]
        category_profiles = [
            p for p in city_profiles
            if any(self._category_key(category) == category_key for category in p.categories)
        ]
        synthetic_count = sum(profile.synthetic for profile in profiles)
        if synthetic_count == len(profiles) and profiles:
            source_label = "SYNTHETIC DEMO CATALOG"
        elif synthetic_count:
            source_label = "ANONYMIZED SOURCE + SYNTHETIC"
        else:
            source_label = "ANONYMIZED SOURCE DATA"
        if not category_profiles:
            return ContractorSearchResult(
                outcome="CATEGORY_NOT_FOUND",
                message=f"В каталоге города {request.city} нет подрядчиков категории «{request.category}».",
                requested_limit=request.limit,
                candidate_count=0,
                matched_count=0,
                source_label=source_label,
            )

        rejections: dict[str, int] = {}
        eligible: list[tuple[tuple, ContractorProfile]] = []
        for profile in category_profiles:
            reasons = self._rejection_reasons(profile, request)
            for reason in reasons:
                rejections[reason] = rejections.get(reason, 0) + 1
            if reasons:
                continue
            eligible.append((self._sort_key(profile, request), profile))

        if not eligible:
            detail = self._rejection_text(rejections)
            return ContractorSearchResult(
                outcome="NO_MATCHES",
                message=f"В городе есть {len(category_profiles)} кандидатов категории «{request.category}», но ни один не проходит условия: {detail}.",
                requested_limit=request.limit,
                candidate_count=len(category_profiles),
                matched_count=0,
                rejection_reasons=rejections,
                source_label=source_label,
            )

        eligible.sort(key=lambda pair: pair[0])
        cards = [self._card(profile, request) for _, profile in eligible[:request.limit]]
        available_count = len(eligible)
        if available_count < request.limit:
            if rejections:
                message = (
                    f"Подходящих подрядчиков: {available_count} из запрошенных {request.limit}. "
                    f"Остальные кандидаты исключены: {self._rejection_text(rejections)}."
                )
            else:
                message = (
                    f"В каталоге нашлось {available_count} подходящих подрядчиков; "
                    f"в этой категории и городе нет ещё {request.limit - available_count} карточек."
                )
        elif rejections:
            shown = min(available_count, request.limit)
            message = (
                f"Показали {shown} карточки из {available_count} подходящих; порядок детерминирован. "
                f"Другие профили исключены, в том числе: {self._rejection_text(rejections)}."
            )
        elif available_count > request.limit:
            message = f"Показали {request.limit} карточки из {available_count} подходящих; порядок детерминирован по цене и совпадению условий."
        else:
            message = f"Подобрали {available_count} подрядчиков по городу, дате, формату, категории и бюджету."
        return ContractorSearchResult(
            outcome="MATCHES",
            message=message,
            requested_limit=request.limit,
            candidate_count=len(category_profiles),
            matched_count=available_count,
            cards=cards,
            rejection_reasons=rejections,
            source_label=source_label,
        )

    def _rejection_reasons(self, profile: ContractorProfile, request: ContractorSearchRequest) -> list[str]:
        reasons: list[str] = []
        if request.event_date in profile.busy_dates:
            reasons.append("booked_on_date")
        if profile.price_from_kzt > request.budget_kzt:
            reasons.append("over_budget")
        event_format = self._format_key(request.event_type)
        profile_formats = {self._format_key(value) for value in profile.event_formats}
        if event_format not in profile_formats:
            reasons.append("format_mismatch")
        if request.duration_hours is not None and profile.max_hours is not None and request.duration_hours > profile.max_hours:
            reasons.append("duration_exceeded")
        if request.language and self._language_key(request.language) not in {
            self._language_key(value) for value in profile.languages
        }:
            reasons.append("language_mismatch")
        return reasons

    def _sort_key(self, profile: ContractorProfile, request: ContractorSearchRequest) -> tuple:
        price_headroom = (request.budget_kzt - profile.price_from_kzt) / request.budget_kzt
        semantic_overlap = self._description_overlap(request.event_type, profile.description)
        if request.duration_hours is None or profile.max_hours is None:
            duration_fit = Decimal("0")
        else:
            duration_fit = Decimal("1") - ((profile.max_hours - request.duration_hours) / profile.max_hours)
        score = (price_headroom * Decimal("0.55")) + (semantic_overlap * Decimal("0.25")) + (duration_fit * Decimal("0.20"))
        return (-score, profile.price_from_kzt, profile.id)

    def _card(self, profile: ContractorProfile, request: ContractorSearchRequest) -> ContractorCard:
        price_gap = request.budget_kzt - profile.price_from_kzt
        price_prefix = "Ориентировочная цена" if profile.price_imputed else "Цена"
        price_phrase = (
            f"{price_prefix} от {self._money(profile.price_from_kzt)} ₸ ниже лимита на {self._money(price_gap)} ₸"
            if price_gap > 0 else f"{price_prefix} от {self._money(profile.price_from_kzt)} ₸ точно укладывается в лимит"
        )
        format_phrase = f"принимает формат «{request.event_type}»"
        qualifiers = [price_phrase, format_phrase]
        if request.language:
            qualifiers.append(f"работает на языке «{request.language}»")
        if profile.synthetic:
            qualifiers.append("синтетический demo-профиль")
        if profile.city_imputed:
            qualifiers.append("город восстановлен при подготовке датасета")
        first_sentence = "; ".join(qualifiers) + "."
        second_parts = []
        if request.duration_hours is not None:
            if profile.max_hours is None:
                second_parts.append("Услуга не привязана к максимальному времени присутствия")
            else:
                second_parts.append(
                    f"лимит {self._hours(profile.max_hours)} ч покрывает запрос на {self._hours(request.duration_hours)} ч"
                )
        description = self._description_sentence(profile.description, request.event_type)
        if description:
            second_parts.append(f"в профиле указано: «{description}»")
        explanation = first_sentence.rstrip(".")
        if second_parts:
            explanation += "; " + "; ".join(second_parts) + "."
        else:
            explanation += "."
        return ContractorCard(
            contractor_id=profile.id,
            name=profile.anon_name,
            category=profile.categories[0],
            city=profile.city,
            price_from_kzt=profile.price_from_kzt,
            explanation=explanation,
            synthetic=profile.synthetic,
            city_imputed=profile.city_imputed,
            price_imputed=profile.price_imputed,
            source_label="SYNTHETIC" if profile.synthetic else "ANONYMIZED SOURCE",
        )

    @staticmethod
    def _rejection_text(rejections: dict[str, int]) -> str:
        labels = {
            "booked_on_date": "заняты на эту дату",
            "over_budget": "выше бюджета",
            "format_mismatch": "не берут этот формат",
            "duration_exceeded": "не подходят по длительности",
            "language_mismatch": "не работают на нужном языке",
        }
        if not rejections:
            return "причину нельзя определить по текущим данным"
        return ", ".join(f"{count} {labels.get(code, code)}" for code, count in sorted(rejections.items()))

    @classmethod
    def _description_overlap(cls, event_type: str, description: str) -> Decimal:
        tokens = {token.casefold() for token in _TOKEN_RE.findall(event_type) if token.casefold() not in _STOP_WORDS}
        words = {token.casefold() for token in _TOKEN_RE.findall(description) if token.casefold() not in _STOP_WORDS}
        if not tokens:
            return Decimal("0")
        return Decimal(len(tokens & words)) / Decimal(len(tokens))

    @classmethod
    def _description_sentence(cls, description: str, event_type: str) -> str:
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", description) if part.strip()]
        if not sentences:
            return ""
        query_tokens = {
            token.casefold() for token in _TOKEN_RE.findall(event_type) if token.casefold() not in _STOP_WORDS
        }
        indexed_sentences = list(enumerate(sentences))
        indexed_sentences.sort(
            key=lambda item: (
                -len(query_tokens & {token.casefold() for token in _TOKEN_RE.findall(item[1])}),
                item[0],
            )
        )
        excerpt = indexed_sentences[0][1].rstrip(".!? ")
        if len(excerpt) > 180:
            excerpt = excerpt[:177].rsplit(" ", 1)[0] + "…"
        return excerpt

    @staticmethod
    def _money(value: Decimal) -> str:
        if value == value.to_integral_value():
            return f"{int(value):,}".replace(",", " ")
        return f"{value:,.2f}".replace(",", " ")

    @staticmethod
    def _hours(value: Decimal) -> str:
        return format(value.normalize(), "f")

    @classmethod
    def _city_key(cls, value: str) -> str:
        key = cls._text_key(value)
        return _CITY_ALIASES.get(key, key)

    @classmethod
    def _category_key(cls, value: str) -> str:
        key = cls._text_key(value)
        return _CATEGORY_ALIASES.get(key, key)

    @classmethod
    def _format_key(cls, value: str) -> str:
        key = cls._text_key(value)
        return _FORMAT_ALIASES.get(key, key)

    @classmethod
    def _language_key(cls, value: str) -> str:
        key = cls._text_key(value)
        return _LANGUAGE_ALIASES.get(key, key)

    @staticmethod
    def _text_key(value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().casefold().replace("ё", "е"))
