---
name: tez-akademik-dil-kontrol
user-invocable: true
summary: "Tez yazmada akademik dili ve insan gibi yazıldığını kontrol eden skill"
description: |
  Bu skill, tez ya da akademik metinlerin:
  - akademik dil kullanımı,
  - insana benzeyen akıcılık ve ifade,
  - netlik ve mantıksal tutarlılık,
  - gereksiz tekrar veya mekanik AI tarzı ifadeler içermediğini kontrol etmek için kullanılır.
  Use when you want a concise review of academic writing style and naturalness.

inputs:
  - name: text
    description: "İncelenecek tez metni veya akademik yazı"
    required: true

steps:
  - name: analyse-style
    description: "Metnin akademik dil ve insan benzeri ifade yapısını değerlendir"
    type: output
    output: |
      Metni şu kriterlere göre değerlendir:
      1. Dil akademik ve uygun mu?
      2. İfade akıcı ve doğal mı?
      3. AI üretimi izleri (fazla resmiyet, tekrar eden kalıplar, mekanik cümleler) var mı?
      4. Sorunlu ifadeler varsa nedenleri ve iyileştirme önerilerini belirt.
      5. Gerekirse metnin bir bölümünü daha doğal ve akademik hale getirilmiş örnek cümleyle yeniden yaz.

examples:
  - input: |
      Bu çalışma kapsamında elde edilen veriler analiz edilmiştir ve sonuçlar incelenmiştir.
    output: |
      - Akademik dil genel olarak uygun, ancak cümle biraz pasif ve tekrarlı.
      - "Bu çalışma kapsamında elde edilen veriler analiz edilmiştir ve sonuçlar incelenmiştir." yerine daha doğal ve akıcı bir ifade:
        "Bu çalışmada elde edilen veriler analiz edilmiş ve sonuçlar değerlendirilmiştir."
  - input: |
      Modelin doğruluğu yüksektir. Sonuçlar anlamlıdır.
    output: |
      - Cümleler çok kısa ve bağlamsız; akademik metinde daha açıklayıcı ve ilişkilendirici ifade tercih edilir.
      - Öneri: "Model yüksek doğruluk göstermiş ve elde edilen sonuçlar anlamlı bulunmuştur."
---

Aşağıdaki metni değerlendir:

{{text}}
