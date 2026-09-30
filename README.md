# GitHub Pages 台股網頁版

公開內容僅為 `pages/` 與程式產生的篩選行情、日 K、ZIP，不發佈本機路徑、日誌或登入資料。
網頁同時使用原本 SREngine 預先計算支撐壓力分析：現價（資料日收盤）、漲跌幅、觸及及守住機率、歷史測試次數、趨勢、ATR 距離、最近支撐／壓力與關鍵位數。以只做多的最近支撐為機率及事件統計對象，關鍵位距離帶為 0.5–5 ATR。缺少關鍵位或模型時顯示空值而非零機率。ZIP 額外包含 analysis.csv、analysis.json，機率原值範圍為 0–1。
機率沿用原專案模型，未另做台股校準；未還原價格與有限的歷史資料會影響分析。這些是模型估計，不是保證胜率。
本機 Flask 版保留；Pages 不需要 Flask，也不提供訪客即時抓取按鈕。

多頭採任一成立（v4）：頭頭高底底高，或三線 MA5 > MA10 > MA20，或四線 MA5 > MA10 > MA20 > MA60。四線包含三線，名單不重複計算。不另要求均線斜率或收盤高於均線，成交量與回檔紅 K 條件保留。
結構分支採最近 60 根有效日 K，以左右各 2 根確認嚴格波段高低點，同類連續轉折取更極端者；最近兩個高點及低點均嚴格提高，最新波段低點未再跌破。尚未確認或同根 K 同時出現高低轉折者不採用；均線分支不必通過此項。

## 發佈

1. 儲存庫 Settings → Pages → Source 選擇 **GitHub Actions**。
2. 推送程式後，到 Actions → **Daily Taiwan Stocks** → Run workflow。
3. 成功後可使用 `https://b9007082-cell.github.io/taiwan-stock-screen/`。

平日台灣時間約 12:00（UTC 04:00）執行盤中暫定篩選，16:30（UTC 08:30）改為收盤確認，也可由儲存庫管理者手動選擇模式觸發。盤中成交量仍須累積至少 1,300 張，不依時間比例調低。
盤中模式使用證交所 MIS 盤中行情（同一服務可查上市與上櫃代碼），不需要 FinMind Sponsor token。公開頁只發布篩選後的代碼、名稱與衍生訊號；即時價格、OHLC 與精確成交量不會寫入公開產物。圖表及支撐壓力沿用最近完整收盤資料。
候選表與個股圖表另顯示 KD(5,3,3) 黃金交叉，以及 MACD(6,13,9) 紅柱；兩者是觀察欄位，不影響原本的入選條件。
所有候選股若跌破月線 MA20，須在 3 個交易日內站回；程式以最近 3 根 K 至少一根價格高於其 MA20 判斷。盤中版會將當下最新價視為最新一根。
GitHub 排程可能延後；公開儲存庫長期沒有活動時排程可能被停用，請留意 Actions。
首次抓取較久；歷史行情使用 Actions cache 減少重複請求。
官方來源或 FinMind 限流、海外主機遭阻擋時，工作流程會失敗，**不覆蓋上次成功網頁**。
網頁一直顯示實際行情日期與產生時間，超過四天會提示檢查休市或更新狀態。
查看 Actions 失敗原因並稍後重跑，不應把舊資料當成當日行情。

## 本機驗證

```powershell
.\.venv\Scripts\python.exe -m unittest scripts.test_tw_daily_update scripts.test_build_pages -v
.\.venv\Scripts\python.exe scripts/build_pages.py --snapshot data/tw_daily/<成功批次>
```

產物 `_site/index.html` 可直接開啟。日 K 圖使用隨站附帶的 Plotly 元件，不依賴外部 CDN。
不指定 `--snapshot` 時會重新抓取最新完整交易日，供 Actions 使用。
請勿把 `.venv`、`.cache`、本機 `data/`、`output/` 或 `.data_dir.txt` 加入公開提交。

官方部署說明：https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages


Based on https://github.com/rosemarycox5334-debug/Detect_support_and_resistance_levels . See LICENSE.
