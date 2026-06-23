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

      6. Sorunlu ifadeler ve öneriler:
         Sorunlu ifadeleri alıntıla, neden sorunlu olduklarını açıkla ve daha iyi akademik alternatif öner.

      7. Örnek yeniden yazım:
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
---

Aşağıdaki metni değerlendir:

{{text}}