# 금액 계산의 정밀도

double로 금액을 다루면 어디서 틀리는지 보고, `BigDecimal`로 고친 뒤에도 남는 함정까지 따라간다. 장마다 15분, 앞 장을 읽었다고 가정한다.

| 장 | 이 장이 답하는 것 |
|---|---|
| [1. double로 금액을 더하면 왜 틀리는가](chapters/01-double-오차.md) | 0.1의 2진 근삿값과 `==` 비교의 실패 |
| [2. BigDecimal은 어떻게 십진 금액을 정확히 담는가](chapters/02-bigdecimal-표현.md) | 비스케일 값·스케일과 생성 경로의 함정 |
| [3. 정확한 BigDecimal끼리 비교하고 나누면 왜 예상과 다른가](chapters/03-bigdecimal-비교-나눗셈.md) | `equals`와 `compareTo`, 나눗셈의 반올림과 나머지 |
