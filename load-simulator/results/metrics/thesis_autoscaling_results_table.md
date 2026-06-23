| Senaryo | Yöntem | Örnek | SLO ihlal dk | Latency SLO dk | Error SLO dk | Avg pod | Max pod | Avg CPU mcores | Max CPU mcores |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| step | HPA | 552 | 10.417 | 10.417 | 0.0 | 28.821 | 60.0 | 3036.13 | 10335.447 |
| step | KEDA | 554 | 28.667 | 28.667 | 0.0 | 21.103 | 60.0 | 2513.419 | 8268.429 |
| step | MLP | 687 | 14.75 | 13.833 | 1.083 | 20.956 | 57.0 | 2368.406 | 9342.671 |
| step | Linear | 675 | 2.583 | 1.75 | 0.833 | 20.733 | 60.0 | 2502.26 | 9770.925 |
| step | SVR | 1131 | 26.917 | 26.917 | 0.333 | 14.934 | 60.0 | 1437.705 | 9757.908 |
| spike | HPA | 100 | 7.417 | 7.417 | 0.083 | 17.14 | 30.0 | 1217.661 | 2550.202 |
| spike | KEDA | 100 | 7.5 | 7.5 | 0.417 | 32.69 | 60.0 | 1866.409 | 4534.317 |
| spike | MLP | 132 | 5.917 | 5.833 | 0.083 | 29.045 | 60.0 | 2179.478 | 6085.393 |
| spike | Linear | 126 | 6.75 | 6.25 | 0.583 | 23.524 | 43.0 | 2100.266 | 5659.654 |
| spike | SVR | 285 | 5.167 | 4.417 | 0.75 | 7.923 | 34.0 | 458.148 | 2269.579 |
| poisson | HPA | 216 | 0.083 | 0.0 | 0.083 | 44.333 | 54.0 | 2966.001 | 3701.607 |
| poisson | KEDA | 216 | 15.917 | 15.917 | 0.333 | 43.528 | 60.0 | 2030.763 | 2845.433 |
| poisson | MLP | 261 | 11.417 | 11.0 | 0.417 | 30.908 | 45.0 | 1542.021 | 2959.197 |
| poisson | Linear | 242 | 2.0 | 1.25 | 0.833 | 17.636 | 22.0 | 1908.67 | 2483.432 |
| poisson | SVR | 402 | 17.083 | 17.083 | 0.583 | 16.689 | 39.0 | 919.269 | 2399.644 |

**Kolon açıklamaları**

- **Senaryo:** Deneyde kullanılan yük tipidir.
- **Yöntem:** Karşılaştırılan autoscaling yaklaşımıdır.
- **Örnek:** Prometheus/export CSV içinde ilgili senaryo-yöntem için kullanılan satır sayısıdır.
- **SLO ihlal dk:** `p95_latency > 0.5` veya `error_rate > 0.05` olduğu toplam süredir.
- **Latency SLO dk:** Sadece p95 gecikme eşiğinin aşıldığı toplam süredir.
- **Error SLO dk:** Sadece hata oranı eşiğinin aşıldığı toplam süredir.
- **Avg pod / Max pod:** Deney sırasında gözlenen ortalama ve maksimum pod sayısıdır.
- **Avg CPU mcores / Max CPU mcores:** Deney sırasında gözlenen ortalama ve maksimum CPU tüketimidir.
