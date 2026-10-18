---
번호: "03"
제목: 정확한 BigDecimal끼리 비교하고 나누면 왜 예상과 다른가
계약버전: 1
입력해시: 91befcff9812025c1f9b362dadb6ef550844bd67d4b27927119d3da04bb6f975
요약: 금액 비교는 compareTo로, 나누어떨어지지 않는 나눗셈은 스케일·반올림 모드·나머지 처리를 정해서 맞춘다는 데까지 왔다. 남긴 문제는 없다.
이월제안: []
---

# 3. 정확한 BigDecimal끼리 비교하고 나누면 왜 예상과 다른가

2장까지 오면 값은 정확하다. 남은 문제는 정확한 값끼리도 비교와 나눗셈에서는 왜 예상과 다른 결과가 나오는가이고, 이 장은 그 두 지점을 정산 배치에서 본다.

## 3.1 10.0과 10.00은 왜 equals로 같지 않은가?

환불 검증 단계는 결제 금액과 환불 금액이 같은지 `equals`로 확인했다. 결제 쪽은 `new BigDecimal("10.00")`, 환불 쪽은 계산 결과로 `10.0`이 들어왔고, 검증은 실패했다. 두 값은 수로서는 같다. 하지만 2장의 표현으로는 다르다. `10.00`은 비스케일 값 1000에 스케일 2이고, `10.0`은 100에 스케일 1이다.

<mark style="background-color:#FFF3B0">`equals`는 값과 스케일을 함께 비교하고, `compareTo`는 수의 크기만 비교한다.</mark> 그래서 `new BigDecimal("10.0").equals(new BigDecimal("10.00"))`은 `false`이고, 같은 두 값의 `compareTo`는 `0`이다. 금액이 같은지 판정할 때는 `compareTo(...) == 0`을 쓴다.

이 차이는 컬렉션에서도 드러난다. `hashCode`도 스케일을 반영하므로 <mark style="background-color:#D3F9D8">`HashSet`에 `10.0`과 `10.00`을 넣으면 원소가 두 개이고, `compareTo`로 정렬하는 `TreeSet`에 넣으면 하나다.</mark> 같은 금액끼리 묶으려 했다면 어느 컬렉션을 쓰느냐에 따라 결과가 갈린다.

흔한 오해는 이것을 버그로 보는 것이다. <mark style="background-color:#FFC9C9">`equals`가 스케일까지 보는 것은 API 문서에 명시된 동작이므로, 스케일이 다를 수 있는 금액을 `equals`로 비교하면 안 된다.</mark> 얻는 것은 표현까지 엄밀한 동등성이고, 잃는 것은 금액 비교에서의 직관이다.

## 3.2 100달러를 셋으로 나누면 왜 예외가 나고, 어떻게 나눠야 하는가?

주문 금액 $100.00을 세 명이 나눠 결제하는 기능에서 첫 구현이 예외를 던졌다. 아래는 그 지점과 고친 코드다.

```java
BigDecimal total = new BigDecimal("100.00");
BigDecimal three = BigDecimal.valueOf(3);

// total.divide(three) → ArithmeticException: Non-terminating decimal expansion; ...
BigDecimal share = total.divide(three, 2, RoundingMode.HALF_EVEN);       // 33.33
BigDecimal last = total.subtract(share.multiply(BigDecimal.valueOf(2))); // 33.34
```

스케일과 반올림 규칙을 받지 않은 `divide`는 정확한 결과를 돌려주려고 한다. 100/3은 33.333…으로 끝나지 않아 정확한 십진 결과가 없으므로, `divide`는 값을 지어내는 대신 `ArithmeticException`을 던진다. <mark style="background-color:#FFF3B0">나누어떨어지지 않는 나눗셈은 결과의 스케일과 반올림 모드를 호출하는 쪽이 정해야 한다.</mark> 2장에서 미뤄 둔 할인 단가 17.991을 센트로 줄이는 `setScale(2, ...)`도 같은 결정을 요구한다.

반올림 모드(rounding mode)는 버려지는 자리를 어떻게 처리할지 정한다. `HALF_UP`은 정확히 절반이면 올리는 익숙한 반올림이다. `HALF_EVEN`은 정확히 절반일 때 남는 끝자리가 짝수가 되는 쪽으로 보내는 은행원 반올림(banker's rounding)이다. <mark style="background-color:#D3F9D8">정수로 반올림하면 2.5는 `HALF_UP`으로 3, `HALF_EVEN`으로 2가 되고, 3.5는 둘 다 4다.</mark> 절반인 값이 자주 나오는 계산에서 `HALF_UP`은 매번 올려 합계가 위로 치우치고, `HALF_EVEN`은 올림과 내림이 섞여 치우침이 줄어든다.

흔한 오해는 반올림 모드만 고르면 끝난다는 생각이다. 33.33을 세 번 더하면 99.99라 1센트가 사라진다. 그래서 위 코드는 앞의 두 명에게 33.33을 매기고, 마지막 사람에게는 총액에서 둘의 몫을 뺀 33.34를 매긴다. <mark style="background-color:#FFC9C9">몫의 합이 원래 금액과 같도록 남는 금액을 누구에게 줄지까지 정해야 정산이 맞는다.</mark>

## 다 읽고 나면

답할 수 있게 된 질문
- 10.0과 10.00은 왜 equals로 같지 않은가? — `equals`는 스케일까지 비교한다. 금액이 같은지는 `compareTo`로 판정한다.
- 100달러를 셋으로 나누면 왜 예외가 나고, 어떻게 나눠야 하는가? — 정확한 십진 결과가 없는 나눗셈이라 예외가 난다. 스케일과 반올림 모드를 지정하고, 남는 금액을 한 사람에게 몰아 합계를 맞춘다.

다음 장으로 넘기는 문제
- 없음. 이 책의 마지막 장이다.
