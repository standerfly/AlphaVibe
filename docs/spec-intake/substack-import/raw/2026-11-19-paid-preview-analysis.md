# 僅預覽判斷分析（2026-11-19，40 篇，只讀 XML）
## 事實
- 兩 feed 條目欄位完全相同：title/description/link/guid/pubDate/enclosure(圖或audio)/content:encoded(+creator)。無 category、無 audience/paywall 欄位或屬性。
- 唯一穩定結構差異：content:encoded 結尾是否為固定 `<p> <a href="https://{host}/p/{slug}"> Read more </a> </p>`。
- FOMO 17/20 有該尾端；3 篇無（Anthropic S-1／Anthropic的增長／Marvell營收翻十倍，皆以「Substack Chat group · KP」結尾，純文字 12k~15k 字）。
- 大叔 18/20 有；無者：「黃仁勳辭職之後」（結尾為免責聲明 ol，7.5k字）、「$MSFT FY2027 Q1」（0字，audio/mpeg enclosure，只有播放器 div）。
- 「$AMD」「Alphabet $GOOGL」純文字僅 9 字（只有播放器 widget＋Read more）；「週報 2026.11.15」38 字（只有嵌入卡片＋Read more）。
- 每日重點 6 篇全部有 Read more；長度 159~1476 字；其中 261117／261113 尾端停在小標題（【HBM/記憶體】、【NVDA供應鏈/估值】）後無內文＝明顯被截斷。
## 推論（無付費帳號，無真值）
- Read more 尾端＝Substack 對非全公開文章（付費牆）在 RSS 截斷並附加的連結；無此尾端＝全文（推論，依據：S-1 等 4 篇無尾端且內容完整含作者結語；paid.xml 另一 feed 也是部分篇有）。
- 風險：paid.xml 中長文（44k字）也有 Read more，故「截斷點在哪」不能用長度判斷。
