---
name: tez-akademik-dil-kontrol
user-invocable: true
summary: "Tez ve akademik metinlerde dil, akıcılık, doğallık ve tartışma niteliğini denetler"
description: |
  Bu skill, Türkçe tez ve akademik metinlerde akademik üslup, akıcılık,
  mantıksal tutarlılık, paragraf bütünlüğü, tekrarlar ve mekanik/kalıplaşmış
  ifade risklerini değerlendirmek için kullanılır. Özellikle bulgular,
  tartışma ve sonuç bölümlerinde metnin doğal, akademik ve savunulabilir
  görünmesini amaçlar.

inputs:
  - name: text
    description: "İncelenecek tez veya akademik metin"
    required: true

steps:
  - name: academic-language-review
    description: "Metni akademik dil, doğallık ve tutarlılık açısından değerlendir"
    type: output
    output: |
      Metni aşağıdaki başlıklarla değerlendir:

      1. Genel değerlendirme:
         Metnin akademik üslup, açıklık ve akıcılık açısından genel durumunu kısaca özetle.

      2. Akademik dil:
         Uygun olmayan, fazla gündelik, fazla iddialı, belirsiz veya gereksiz süslü ifadeleri belirt.

      3. Doğallık ve mekanik ifade riski:
         Tekrar eden kalıpları, aşırı genel ifadeleri, yapay durabilecek cümle yapılarını ve fazla pürüzsüz ama içerikçe zayıf bölümleri değerlendir.
         Kesin biçimde "AI tarafından yazılmıştır" gibi bir yargı verme.

      4. Mantıksal akış:
         Cümleler ve paragraflar arasında neden-sonuç, karşılaştırma, yorum ve sonuç ilişkilerinin yeterince açık olup olmadığını kontrol et.

      5. Bulguların tartışılması:
         Metnin yalnızca bulguları tekrar edip etmediğini; bulguları deney amacı, sistem davranışı, literatür veya çıkarımlarla ilişkilendirip ilişkilendirmediğini değerlendir.

      6. Ölçüm ve karşılaştırma doğruluğu:
         - "Başarılı", "iyi", "kötü" gibi ifadeler yerine nicel veriler (% fark, mutlak değer) kullanıldı mı?
         - Üç yaklaşım (HPA, KEDA, ML) adil şekilde karşılaştırıldı mı?
         - Tablo ve grafiklere atıf yapılmış mı?

      7. Tanım Tutarlılığı:
         - Teknik terimler (pod, HPA, KEDA, latency, RPS vb.) ilk kullanımda açıklanmış mı?
         - Aynı kavram farklı adlarla (ör: "gecikme" vs "latency") karışık kullanılmış mı?
         - Kısaltmalar (ör: SLO, HPA) ilk kez kullanımında uzun adıyla verilmiş mi?

      8. Editten Çatı Kullanımı:
         - "Yapıldı", "edildi", "oluşturuldu" ifadeleri çok mu tekrar ediliyor?
         - Aktif çatıya (doer + action) geçilebilir mi? (ör: "Veriler toplanıldı" → "Prometheus verileri topladı")
         - Değişiklik yarın mı? Yazının akıcılığı artacak mı?

      9. Sorunlu ifadeler ve öneriler:
         Sorunlu ifadeleri alıntıla, neden sorunlu olduklarını açıkla ve daha iyi akademik alternatif öner.

      10. Örnek yeniden yazım:
         Gerektiğinde yalnızca sorunlu cümle veya kısa paragrafı daha doğal, açık ve akademik bir dille yeniden yaz.
         Tüm metni baştan yazma; anlamı ve yazarın niyetini koru.

      Yanıt dili Türkçe olsun. Eleştiriler kısa, doğrudan ve uygulanabilir olsun.

examples:
  - input: |
      Bu çalışma kapsamında elde edilen veriler analiz edilmiştir ve sonuçlar incelenmiştir.
    output: |
      Genel olarak akademik dile uygun olsa da cümlede tekrar ve zayıf fiil kullanımı vardır.
      "Analiz edilmiştir" ve "incelenmiştir" ifadeleri benzer işlev gördüğü için cümle daha sıkı kurulabilir.

      Öneri:
      "Bu çalışmada elde edilen veriler analiz edilmiş ve sonuçlar değerlendirilmiştir."

  - input: |
      Sonuçlar oldukça başarılıdır ve sistem iyi çalışmıştır.
    output: |
      Bu ifade akademik açıdan fazla genel ve gerekçesizdir. "Başarılı" ve "iyi çalışmıştır" gibi ifadeler ölçütle desteklenmediğinde zayıf görünür.

      Öneri:
      "Elde edilen sonuçlar, sistemin seçilen performans ölçütleri açısından kararlı bir davranış sergilediğini göstermektedir."

  - input: |
      HPA yaklaşımı iyi performans göstermiştir, KEDA ise daha kötüdür.
    output: |
      Sonuç: Nicel veriler eksiktir. Karşılaştırma "iyi" ve "kötü" gibi belirsiz terimler içermektedir.
      
      Akademik açı: Hangi metriklerde? Fark ne kadar? Tablo kaçta?
      
      Öneri:
      "Tablo 5'te görüldüğü gibi, HPA yaklaşımı p95 latency'de ortalama 120ms, KEDA ise 145ms ölçümüne ulaşmıştır.
      Bu %20.8'lik fark, gecikme açısından HPA'nın daha hızlı yanıt verdiğini göstermektedir."

  - input: |
      Makine öğrenmesi modeli sistem davranışını öğrenmiştir.
    output: |
      Problem: "Öğrenmiştir" ifadesi belirsizdir. Hangi modelde? Ne kadar iyi (R², MAE)?
      
      Öneri:
      "MLP modeli eğitim aşamasında R² = 0.87, test verisi üzerinde R² = 0.82 değerlerine ulaşmıştır,
      bu da geliştirilen modelin sistem yükünü tahmin etme kapasitesini göstermektedir."

  - input: |
      Bu çalışmada HPA ve KEDA karşılaştırması yapılmıştır. HPA, Horizontal Pod Autoscaler'ı temsil etmektedir. Otopark ölçeklendirme sistemi genellikle gecikme ölçütüne bağlı olarak karar verir. İlk deneyde latency'ye bakılmıştır.
    output: |
      Problem: Tanım tutarlılığı eksik ve tekrarlanıyor.
      1. "HPA" ilk kez "Horizontal Pod Autoscaler" olarak tanımlanmış (✓)
      2. Sonra "Otopark ölçeklendirme" deniyor (?) — yanlış terim
      3. "Latency" vs "gecikme" karışık kullanılıyor (terminoloji tutarsızlığı)
      
      Öneri:
      "Bu çalışmada Kubernetes ortamında Horizontal Pod Autoscaler (HPA) ve KEDA karşılaştırması yapılmıştır. Her iki sistem de pod sayısını dinamik olarak ayarlayarak (dinamik ölçeklendirme), sistem yükü altında hizmet gecikmesi (latency) gibi performans ölçütlerini etkilemektedir. İlk deneyde, sistem yükü altında ortalama p95 latency değerleri ölçülmüştür."

  - input: |
      Veriler toplandı, modeller eğitildi, sonuçlar değerlendirildi ve raporlar yazıldı.
    output: |
      Problem: Editten çatı (pasif fiil) çok fazla tekrarlanıyor. Cümle mekanik ve monoton görülüyor.
      
      Iyileştirme (aktif çatı tercih):
      "Prometheus'tan toplanan sistem metrikleri, scikit-learn kullanılarak üç farklı ML modeli 
      (Linear Regression, SVR, MLP) eğitiminde kullanıldı; her modelin R² ve MAE ölçütleri 
      karşılaştırıldıktan sonra en başarılı model seçilmiştir."
      
      Veya daha doğal:
      "Deneysel analiz, Prometheus'tan toplanan metrikler, üç ML modelinin performansı 
      ve nihai seçim kriteri temel alınarak yürütülmüştür."

---

Aşağıdaki metni değerlendir:

{{text}}

---

## 📋 Bölüm Türlerine Göre Hızlı Kontrol Listesi

### Bulgular (Results) Bölümü
- [ ] Rakamlar açık ve karşılaştırılabilir mi? (tablo/grafik referanslı)
- [ ] "İyi", "kötü" gibi belirsiz ifadeler var mı?
- [ ] Her bulgu neden-sonuç bağlantılı mı?

### Tartışma (Discussion) Bölümü
- [ ] Bulgular sadece tekrarlanmış mı yoksa açıklanmış mı?
- [ ] Neden HPA'nın KEDA'dan daha hızlı olduğu açıklanmış mı?
- [ ] Sonuçların sınırlamaları (test ortamı, workload tipi) belirtilmiş mi?

### Sonuç (Conclusion) Bölümü
- [ ] Ana bulgulardan doğru çıkarımlar yapılmış mı?
- [ ] Geleceğe yönelik çalışmalar realistik ve ilgili mi?
- [ ] Kısaltmalar ve tekil ifadeler tutarlı mı?