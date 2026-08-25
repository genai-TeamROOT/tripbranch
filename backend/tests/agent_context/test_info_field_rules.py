"""question_type별 필드 추출 규칙을 실제 TourAPI 응답 모양으로 검증한다.

여기서 쓰는 raw_intro 키 이름은 detailIntro2가 contentTypeId별로 내려주는 실제
필드명이다. 임의의 키로 테스트하면 규칙이 통과해도 실 응답에서는 아무것도
못 뽑는다.
"""

import pytest

from app.agent_context.info_field_rules import clean_text, extract_info_fields
from app.agent_context.info_schemas import InfoQuestionType
from app.domain.models import PlaceDetails
from app.providers.stub import FakePlaceProvider


def _details(
    *,
    content_type_id: str = "14",
    overview: str | None = None,
    homepage: str | None = None,
    telephone: str | None = None,
    address: str | None = None,
    operating_hours: str | None = None,
    rest_date: str | None = None,
    raw_intro: dict[str, object] | None = None,
    parking: str | None = None,
    parking_fee: str | None = None,
    fee: str | None = None,
    baby_carriage: str | None = None,
    pet: str | None = None,
    credit_card: str | None = None,
    restroom: str | None = None,
    **barrier_free: str | None,
) -> PlaceDetails:
    return PlaceDetails(
        content_id="126508",
        content_type_id=content_type_id,
        title="경복궁",
        address=address,
        overview=overview,
        homepage=homepage,
        telephone=telephone,
        operating_hours=operating_hours,
        rest_date=rest_date,
        raw_common={},
        raw_intro=raw_intro or {},
        provider="tour_api",
        parking=parking,
        parking_fee=parking_fee,
        fee=fee,
        baby_carriage=baby_carriage,
        pet=pet,
        credit_card=credit_card,
        restroom=restroom,
        **barrier_free,
    )


class TestOperatingHours:
    def test_운영시간과_휴무일을_함께_뽑는다(self) -> None:
        details = _details(operating_hours="09:00~18:00", rest_date="매주 화요일")

        assert extract_info_fields("operating_hours", details) == {
            "operating_hours": "09:00~18:00",
            "rest_date": "매주 화요일",
        }

    def test_없는_필드는_키_자체를_넣지_않는다(self) -> None:
        details = _details(operating_hours="09:00~18:00", rest_date=None)

        assert extract_info_fields("operating_hours", details) == {
            "operating_hours": "09:00~18:00"
        }

    def test_값이_전부_없으면_빈_dict다(self) -> None:
        assert extract_info_fields("operating_hours", _details()) == {}


class TestFee:
    """요금은 provider가 정규화해둔 PlaceDetails.fee에서 읽는다.

    contenttypeid별 키(usefee/usefeeleports/usetimefestival)를 어느 것으로 골랐는지는
    provider의 책임이라 여기서 검증하지 않는다 —
    test_place_details_normalized_fields.py가 그쪽을 덮는다.
    """

    def test_정규화된_요금을_계약_키로_옮긴다(self) -> None:
        details = _details(fee="어른 3,000원")

        assert extract_info_fields("fee", details) == {"fee": "어른 3,000원"}

    def test_요금_값이_없으면_빈_dict다(self) -> None:
        details = _details(parking="가능")

        assert extract_info_fields("fee", details) == {}

    def test_raw_intro만_있으면_뽑지_않는다(self) -> None:
        """옛 경로를 지웠는지 못 박는다.

        두 경로가 함께 살아 있으면 같은 질문이 provider에 따라 다르게 답한다.
        """
        details = _details(raw_intro={"usefee": "어른 3,000원"})

        assert extract_info_fields("fee", details) == {}


class TestParking:
    def test_주차와_주차요금을_각각_뽑는다(self) -> None:
        details = _details(parking="주차 가능", parking_fee="무료")

        assert extract_info_fields("parking", details) == {
            "parking": "주차 가능",
            "parking_fee": "무료",
        }

    def test_주차요금만_없으면_주차만_뽑는다(self) -> None:
        details = _details(parking="10대 가능")

        assert extract_info_fields("parking", details) == {"parking": "10대 가능"}

    def test_HTML이_섞인_원문도_정리한다(self) -> None:
        details = _details(parking="가능<br>요금 (30분 1,500원)")

        assert extract_info_fields("parking", details) == {
            "parking": "가능 요금 (30분 1,500원)"
        }

    def test_raw_intro만_있으면_뽑지_않는다(self) -> None:
        details = _details(raw_intro={"parkingculture": "주차 가능"})

        assert extract_info_fields("parking", details) == {}


class TestFacility:
    """편의시설도 provider 정규화 필드에서 읽는다(D-060).

    유형별 키(chkbabycarriageculture/chkcreditcardfood 등) 선택은 provider 책임이라
    test_place_details_normalized_fields.py가 덮는다.
    """

    def test_편의시설_항목을_모두_뽑는다(self) -> None:
        details = _details(
            baby_carriage="가능", pet="불가", credit_card="가능", restroom="있음"
        )

        assert extract_info_fields("facility", details) == {
            "baby_carriage": "가능",
            "pet": "불가",
            "credit_card": "가능",
            "restroom": "있음",
        }

    def test_일부만_있으면_있는_것만_뽑는다(self) -> None:
        details = _details(pet="불가")

        assert extract_info_fields("facility", details) == {"pet": "불가"}

    def test_없음도_값으로_낸다(self) -> None:
        """`없음`은 빈 값과 다르다 — "정보가 없다"가 아니라 "없다고 답했다"다."""
        details = _details(baby_carriage="없음")

        assert extract_info_fields("facility", details) == {"baby_carriage": "없음"}

    def test_raw_intro만_있으면_뽑지_않는다(self) -> None:
        details = _details(raw_intro={"chkpetculture": "불가"})

        assert extract_info_fields("facility", details) == {}


class TestLocationInfo:
    def test_주소와_전화번호를_뽑는다(self) -> None:
        details = _details(address="서울 종로구 사직로 161", telephone="02-3700-3900")

        assert extract_info_fields("location_info", details) == {
            "address": "서울 종로구 사직로 161",
            "telephone": "02-3700-3900",
        }


class TestGeneralInfo:
    def test_개요와_홈페이지를_뽑는다(self) -> None:
        details = _details(
            overview="조선의 법궁이다.", homepage="http://www.royalpalace.go.kr"
        )

        assert extract_info_fields("general_info", details) == {
            "overview": "조선의 법궁이다.",
            "homepage": "http://www.royalpalace.go.kr",
        }


class TestEvent:
    def test_event는_이_경로에서_아무것도_뽑지_않는다(self) -> None:
        # searchFestival2 별도 연동이 필요해 호출부가 unsupported로 걸러낸다.
        details = _details(raw_intro={"usefee": "무료"})

        assert extract_info_fields("event", details) == {}


class TestFakeProviderCarriesIntro:
    """Fake의 raw_intro가 비면 추출 로직이 한 줄도 안 돈 채 테스트가 통과한다.

    이 저장소에서 반복된 "조용한 fake" 실패 유형이다. Fake가 소비 측이 실제로
    읽는 키를 계속 들고 있는지 여기서 못 박는다 — 아래가 깨지면 Fake를 고쳐야지
    테스트를 지우면 안 된다.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("content_id", "content_type_id", "question_type"),
        [
            ("fake-museum-1", "14", "fee"),
            ("fake-museum-1", "14", "parking"),
            ("fake-museum-1", "14", "facility"),
            ("fake-cafe-1", "39", "parking"),
            ("fake-cafe-1", "39", "facility"),
        ],
    )
    async def test_fake_상세로도_필드가_비지_않는다(
        self,
        content_id: str,
        content_type_id: str,
        question_type: InfoQuestionType,
    ) -> None:
        details = (
            await FakePlaceProvider().get_details(content_id, content_type_id)
        ).data

        assert extract_info_fields(question_type, details) != {}


class TestCleanText:
    def test_HTML_태그를_공백으로_바꾼다(self) -> None:
        # <br>을 그냥 지우면 앞뒤 문장이 붙어버린다.
        assert clean_text("조선의 법궁<br>경복궁입니다.") == "조선의 법궁 경복궁입니다."

    def test_HTML_엔티티를_풀어준다(self) -> None:
        assert clean_text("어른 &amp; 어린이") == "어른 & 어린이"

    def test_연속_공백을_하나로_줄인다(self) -> None:
        assert clean_text("  09:00 ~   18:00  ") == "09:00 ~ 18:00"

    def test_빈_문자열은_None이다(self) -> None:
        assert clean_text("   ") is None
        assert clean_text("<br>") is None

    def test_문자열이_아니면_None이다(self) -> None:
        assert clean_text(None) is None
        assert clean_text(3000) is None


class TestBarrierFree:
    """무장애 값(place_barrier_free, D-077)이 facility로 나가는 규칙.

    분류 규칙(prompts/info/question_type_rules.md)이 이미 "휠체어 가능?"을
    facility로 보내고 있어 새 question_type을 만들지 않았다.
    """

    def test_접근로_주출입구_승강기를_한_키로_잇는다(self) -> None:
        details = _details(
            approach_route_raw="출입구까지 턱이 없어 휠체어 접근 가능함",
            entrance_access_raw="주출입구는 경사로가 있어 휠체어 접근 가능함",
            elevator_raw="엘리베이터 있음",
        )

        fields = extract_info_fields("facility", details)

        assert fields["wheelchair_access"] == (
            "출입구까지 턱이 없어 휠체어 접근 가능함"
            " / 주출입구는 경사로가 있어 휠체어 접근 가능함"
            " / 엘리베이터 있음"
        )

    def test_조각이_하나면_구분자를_붙이지_않는다(self) -> None:
        details = _details(entrance_access_raw="주출입구는 턱이 없어 휠체어 접근 가능함")

        fields = extract_info_fields("facility", details)

        assert fields["wheelchair_access"] == "주출입구는 턱이 없어 휠체어 접근 가능함"

    def test_세_값이_모두_없으면_키가_생기지_않는다(self) -> None:
        """무장애 목록에 없는 장소가 대부분이다(4개 구 실측 커버리지 19%)."""
        fields = extract_info_fields("facility", _details(restroom="있음"))

        assert "wheelchair_access" not in fields
        assert fields == {"restroom": "있음"}

    def test_원문의_HTML_태그를_정리한다(self) -> None:
        """무장애 원문에는 <br/>이 섞여 있다. 합치기 전에 정리해야 한다."""
        details = _details(
            approach_route_raw="접근로 이용이 쉬움<br />경사로 있음",
            public_transport_raw="대중교통 이용 가능<br/>저상버스 운행",
        )

        fields = extract_info_fields("facility", details)

        assert fields["wheelchair_access"] == "접근로 이용이 쉬움 경사로 있음"
        assert fields["public_transport"] == "대중교통 이용 가능 저상버스 운행"

    def test_휠체어_대여는_출입과_다른_키로_나간다(self) -> None:
        """TourAPI의 `wheelchair`는 출입이 아니라 대여다.

        두 값이 한 키로 섞이면 "휠체어로 들어갈 수 있나요"라는 질문에 대여 여부로
        답하게 된다.
        """
        details = _details(
            entrance_access_raw="주출입구는 턱이 없어 휠체어 접근 가능함",
            wheelchair_rental_raw="대여 가능(1대/안내데스크)",
        )

        fields = extract_info_fields("facility", details)

        assert fields["wheelchair_access"] == "주출입구는 턱이 없어 휠체어 접근 가능함"
        assert fields["wheelchair_rental"] == "대여 가능(1대/안내데스크)"

    def test_일반_화장실과_장애인_화장실을_함께_낸다(self) -> None:
        """앞은 detailIntro2, 뒤는 detailWithTour2에서 온 값이라 뜻이 다르다."""
        details = _details(
            restroom="있음", accessible_restroom_raw="장애인 화장실 있음(남녀 분리)"
        )

        fields = extract_info_fields("facility", details)

        assert fields["restroom"] == "있음"
        assert fields["accessible_restroom"] == "장애인 화장실 있음(남녀 분리)"

    def test_다른_question_type에는_나가지_않는다(self) -> None:
        """무장애 값은 facility 질문의 답이다. 주차 질문에 섞이면 안 된다."""
        details = _details(
            parking="가능 (54대)", accessible_parking_raw="장애인 주차장 있음(9면)"
        )

        assert extract_info_fields("parking", details) == {"parking": "가능 (54대)"}

    def test_유모차는_무장애_값이_있으면_그것만_낸다(self) -> None:
        """두 출처가 같은 사실을 말하는데 값이 서로 반대인 장소가 있다.

        서울공예박물관은 detailIntro2가 "없음", 무장애가 "대여가능(10대)"이다.
        둘 다 내면 카드에 모순된 두 줄이 나란히 보인다.
        """
        details = _details(
            baby_carriage="없음", stroller_rental_raw="대여가능(10대)"
        )

        fields = extract_info_fields("facility", details)

        assert fields["stroller_rental"] == "대여가능(10대)"
        assert "baby_carriage" not in fields

    def test_무장애_값이_없으면_기존_유모차_값을_그대로_낸다(self) -> None:
        """무장애 정보가 없는 장소가 대부분이라 이 경로가 기본이다."""
        fields = extract_info_fields("facility", _details(baby_carriage="가능"))

        assert fields == {"baby_carriage": "가능"}
