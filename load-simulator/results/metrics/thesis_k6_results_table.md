| Senaryo | Yöntem | Koşum | p95 ms | Avg latency ms | Error % | Avg RPS | Total req |
|---|---|---:|---:|---:|---:|---:|---:|
| step | HPA | 4 | 564.5 | 204.1 | 4.12 | 88.6 | 294081 |
| step | KEDA | 4 | 723.7 | 248.1 | 4.32 | 84.7 | 280766 |
| step | MLP | 4 | 498.8 | 190.3 | 4.05 | 88.4 | 291504 |
| step | Linear | 4 | 371.2 | 164.8 | 4.20 | 90.2 | 297536 |
| step | SVR | 4 | 597.3 | 210.8 | 4.07 | 87.4 | 289768 |
| spike | HPA | 1 | 1788.1 | 895.2 | 4.20 | 99.7 | 49407 |
| spike | KEDA | 1 | 1812.7 | 578.6 | 4.04 | 119.5 | 59296 |
| spike | MLP | 1 | 1225.5 | 336.5 | 4.05 | 141.1 | 70012 |
| spike | Linear | 1 | 918.8 | 332.5 | 4.17 | 141.8 | 70216 |
| spike | SVR | 1 | 1638.0 | 908.0 | 3.88 | 99.0 | 49091 |
| poisson | HPA | 1 | 308.2 | 145.0 | 4.03 | 104.5 | 112859 |
| poisson | KEDA | 1 | 1920.6 | 623.2 | 4.13 | 104.5 | 112855 |
| poisson | MLP | 1 | 1227.8 | 405.7 | 4.09 | 100.5 | 108539 |
| poisson | Linear | 1 | 493.5 | 205.4 | 4.04 | 100.5 | 108539 |
| poisson | SVR | 1 | 2068.7 | 800.9 | 4.13 | 100.4 | 108527 |

**Kolon açıklamaları**

- **Senaryo:** Deneyde kullanılan yük tipi. `step` kademeli yük artışını, `spike` ani trafik artışını, `poisson` ise Poisson dağılımlı değişken trafik davranışını ifade eder.
- **Yöntem:** Karşılaştırılan otomatik ölçeklendirme yaklaşımıdır. HPA, KEDA, MLP, Linear Regression ve SVR yöntemlerini içerir.
- **Koşum:** İlgili senaryo-yöntem kombinasyonu için kaç ayrı k6 summary dosyasının tabloya dahil edildiğini gösterir.
- **p95 ms:** İsteklerin yüzde 95'inin altında kaldığı gecikme süresidir. Değerin düşük olması kullanıcı deneyimi açısından daha iyidir.
- **Avg latency ms:** Tüm isteklerin ortalama yanıt süresidir. Genel response time davranışını gösterir.
- **Error %:** k6 sonucuna göre başarısız istek oranıdır. Yüzde olarak verilmiştir.
- **Avg RPS:** Test süresince gerçekleşen ortalama saniyelik istek sayısıdır.
- **Total req:** İlgili koşumlarda gönderilen toplam HTTP istek sayısıdır.
