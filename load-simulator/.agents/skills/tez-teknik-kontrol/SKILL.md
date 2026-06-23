---
name: tez-teknik-kontrol
user-invocable: true
summary: "Kubernetes + ML autoscaling tezinin teknik doğruluğu ve metodoloji tutarlılığını denetler"
description: |
  Bu skill, Kubernetes ve makine öğrenmesi tabanlı otomatik ölçeklendirme 
  tezlerinin teknik detaylarını, metodoloji tutarlılığını ve sonuçların 
  güvenilirliğini değerlendirir. Performans metrikleri, karşılaştırma 
  kriteri, model performansı, deneysel tasarım ve sistem tasarımı ayrıntılarını kontrol eder.
  
  NOT: Bu skill TEKNIK tutarlılık içindir. Dil/yazı kalitesi için 
  tez-akademik-dil-kontrol skill'ini kullanın.

inputs:
  - name: text
    description: "İncelenecek tez ya da bölüm (özellikle Metot, Sonuçlar, Tartışma)"
    required: true
  - name: section_type
    description: "Bölüm türü: metodoloji | sonuçlar | tartışma | genel"
    required: false
    default: "genel"

steps:
  - name: technical-validation
    description: "Tezin Kubernetes + ML alanında teknik tutarlılığını kontrol et"
    type: output
    output: |
      Metni aşağıdaki başlıklarla değerlendir:

      1. Teknik Tanımlar ve Terminoloji:
         - Kubernetes terimler (pod, HPA, KEDA, replica, node, resource request/limit) 
           doğru ve tutarlı kullanılmış mı?
         - Performans metrikleri (p95 latency, error rate, RPS, CPU mcores) 
           birim ve tanım ile doğru mı?
         - ML terimleri (R², MAE, MSE, overfitting, prediction error) 
           standart tanımlarla uyumlu mu?

      2. Deneysel Tasarım ve Senaryo Tutarlılığı:
         - Yükleme senaryoları (Spike, Poisson, Step load) neden seçildi açık mı?
         - Her yaklaşım (HPA, KEDA, ML) aynı test koşullarında mı değerlendirildi?
         - Eğitim/Test veri split oranları açık ve makul mı (%80/%20 veya benzeri)?

      3. Metriklerin Doğruluğu ve Tutarlılığı:
         - Referans metrikleri (p95, error rate gibi) konsisten tanımlanmış mı?
         - SLO (Service Level Objective) tanımı açık ve ölçülebilir mi?
         - Model metrikleri (R², MAE) hem eğitim hem test seti için verilmiş mi?

      4. Karşılaştırma Adilliği:
         - Her yaklaşım eşit "bütçe" altında mı çalıştırıldı? 
           (örn: aynı pod sayısı limitleri, aynı metrikler)
         - Farklı koşullar varsa, fark açıkça belirtilmiş mi?
         - "A, B'den X% daha iyi" ifadesi hangi veriye dayalı?

      5. Model Performansı ve Güvenilirlik:
         - Hiperparameter seçimi nasıl yapıldı? (random search, grid search, manuel?)
         - Overfitting/Underfitting riski değerlendirilmiş mi?
         - Cross-validation veya validation seti kullanılmış mı?

      6. Sistem Davranışı Tanımı:
         - CPU, Memory, Pod sayısı gibi kaynaklar neden seçildi?
         - Min/Max pod sınırları ve scaling thresholds neden bu değerler?
         - Prometheus metric collection aralığı (scrape interval) etkileyebilir mi?

      7. Teknik Sorunlar ve Uyarılar:
         - İstatistiksel anlamlılık test edilmiş mi? (birden çok run yapılıp sonuçlar değişken mi?)
         - Edge case'ler (gradual yük, ani yük, sistem başlangıcı) tartışılmış mı?
         - Ölçüm hatası veya sistemik bias olabilir mi?

      8. Sonuçların Genelleştirilebilirliği:
         - Sonuçlar test ortamına (özel config) mı bağlı, yoksa genel mi?
         - Başka Kubernetes konfigürasyonunda da aynı sonuç beklenir mi?
         - Scaling decision algoritması başka workload'lara uygulanabilir mi?

      Yanıt dili Türkçe olsun. Her bulgu sahası belirtilsin.

examples:
  - input: |
      HPA yaklaşımı 100 concurrent user altında çalıştırıldı, KEDA ise 200 concurrent user altında test edildi.
    output: |
      🚨 PROBLEM: Deneysel tasarım hatası
      
      HPA ve KEDA karşılaştırması adil değildir. Farklı yükleme seviyelerinde test edilmiştir.
      
      Teknik sorun: Bu durum KEDA'nın daha fazla pod allocate etmek zorunda kalması anlamına gelir.
      Gerçek performans farkı belirsiz kalır.
      
      Düzeltme: Tüm yaklaşımları AYNI yükleme profilinde (örn: 100 concurrent user × 300 saniye)
      test edin. Sonuçları karşılaştırırken bu bilgiyi açıkça belirtin.

  - input: |
      Model performansı R² = 0.95'e ulaşmıştır. Bu çok iyi bir sonuçtur.
    output: |
      ⚠️ UYARI: Eksik bilgi
      
      Test seti R²'si verilmiş mi? Eğitim seti R² = 0.95 overfitting göstergesi olabilir.
      
      Kontrol listesi:
      - [ ] Training R² ve Test R² ayrı ayrı verilmiş mi?
      - [ ] Aralarında %5'ten fazla fark varsa overfitting riski var mı?
      - [ ] Cross-validation yapılmış mı?
      
      Örnek yazım:
      "MLP modeli eğitim seti üzerinde R² = 0.92, validation seti üzerinde R² = 0.87 elde etmiştir. 
      %5'lik fark, modelin biraz overfitting riski taşıdığını göstermektedir."

  - input: |
      Pod sayısı 1 ile 50 arasında ölçeklenebilir olarak ayarlandı.
    output: |
      ℹ️ BİLGİ TALEBİ
      
      Teknik açıdan bu sınırlar makul mı? Kontrol edin:
      - [ ] Minimum pod=1 neden seçildi? (Application startı kaç saniye alıyor?)
      - [ ] Maximum pod=50 resource limiti mi yoksa kapasite testi mi?
      - [ ] CPU/Memory request-limit oranları tutarlı mı?
      
      Eğer tezde bunlar açıklanmamışsa, Metodoloji bölümünde belirtin:
      "Pod scaling sınırları (min=1, max=50), test ortamının resource kapasitesi 
      ve container startup süresine (~2s) bağlı olarak belirlenmiştir."

  - input: |
      KEDA kural tabanlı ölçeklendirme için 5 kural tanımlanmış: 
      - CPU > %80 ise +1 pod
      - Latency > 150ms ise +2 pod
      - ...
    output: |
      ✅ İYİ: Kurallar tanımlanmış
      
      Ek kontrol:
      - [ ] Bu kurallar neden seçildi? (deneme yanılma, literatür, SLO?)
      - [ ] Kurallar çatışıyor mu? (aynı anda iki kural trigger olursa?)
      - [ ] Cool-down/debounce süresi var mı? (sallanmayı önlemek için)
      
      Eğer eksikse açıkla:
      "KEDA kuralları SLO hedeflerine (p95 latency ≤ 200ms, error rate ≤ 1%) 
      bağlı olarak belirlendi ve 30 saniyelik cool-down dönemine sahiptir."

---

## Kubernetes + ML Autoscaling İçin Hızlı Kontrol Listesi

Bölüm yazarken hızlı kontrol için:

### Metodoloji Bölümü
- [ ] Test ortamı spesifikasyonu açık mı? (Node sayısı, CPU/Memory, Kubernetes versiyonu)
- [ ] Metrikleri hangi aralıkta toplaması belirtilmiş mi? (Prometheus scrape_interval)
- [ ] HPA/KEDA parametreleri tam tanımlanmış mı?
- [ ] ML modeli eğitim parametreleri (learning rate, iterations, random_state) verilmiş mi?

### Sonuçlar Bölümü
- [ ] Her ölçüm birden çok run'ın ortalaması mı? (std dev da verildi mi?)
- [ ] Tablolara atıf yapılıyor mu? ("Tablo X'te görüldüğü gibi")
- [ ] Grafik eksen etiketleri (label, unit) açık mı? (örn: "Latency (ms)")

### Tartışma Bölümü
- [ ] Neden A, B'den daha iyi? Mekanik açıklanmış mı?
- [ ] Sonuçlar sadece bu sistemde mi geçerli, yoksa genelleştirilebilir mi?
- [ ] Limitasyonlar (test ortamı, workload tipi) açıkça belirtilmiş mi?

---

Aşağıdaki metni değerlendir:

{{text}}