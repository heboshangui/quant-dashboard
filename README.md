# 📊 A股量化分析工具

面向纯新手的 A 股量化工具箱，**技术面 + 基本面**一起看，边用边学。

---

## 🗂️ 项目结构

```
quant-dashboard/
├── app.py              # Flask 主应用（数据获取 + 指标计算 + API）
├── requirements.txt    # Python 依赖
├── README.md           # 本文件
├── templates/
│   ├── dashboard.html  # 自选股仪表盘（首页）
│   ├── selector.html   # 选股器页面
│   ├── learn.html      # 新手学院（内置教程）
│   └── chart.html      # K线图页面（Plotly 交互图表）
└── static/            # 静态资源（可选扩展）
```

---

## 🚀 快速开始

### 本地运行

```bash
# 1. 创建虚拟环境
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动服务
python app.py
# 🌐 访问 http://127.0.0.1:5001
```

### 依赖说明

| 包 | 用途 |
|---|---|
| Flask | Web 框架 |
| akshare | A股数据（东方财富等，实时免费） |
| plotly | K线图与指标图表（交互式） |
| pandas | 数据处理 |
| requests | HTTP 请求 |

---

## 📖 功能说明

### 1️⃣ 自选股仪表盘（首页）
- 默认展示：康强电子(sz002119)、云赛智联(sh600602)、华建集团(sh600629)
- 每只股票显示：
  - 实时价格、涨跌幅、成交量
  - **基本面卡片**：PE、PB、总市值、流通市值、营收增速
  - **技术面卡片**：MACD柱方向、KDJ金叉/死叉、均线多头/空头排列、RSI
  - **综合信号**：观望 → 谨慎 → 关注 → 看好（0-4分）
- 所有指标旁有「?」悬停提示，新手友好

### 2️⃣ 选股器
支持 5 种筛选条件，每次最多返回 20 条：
- 🔥 涨停股（今日涨幅 ≥ 9.9%）
- 📈 突破年高（股价创250日新高）
- 📊 突破半年高（股价创120日新高）
- ✅ MACD 金叉
- ✅ KDJ 金叉
- 📊 均线多头排列（MA5 > MA10 > MA20）

### 3️⃣ 新手学院
内置 6 课图文教程：
1. MACD 指标详解（金叉/死叉/柱状图）
2. KDJ 指标详解（超买/超卖/金叉死叉）
3. 均线系统（多头排列/空头排列/粘合发散）
4. PE 和 PB（估值判断方法）
5. RSI 指标（超买超卖/背离）
6. 基本面分析入门（净利润/营收/市值）

### 4️⃣ K线图（交互式）
- K线蜡烛图 + MA5/10/20 均线
- MACD（主图 + DIF/DEA 线 + 柱状图）
- KDJ（K/D/J 三线）
- RSI（相对强弱指数）

---

## ☁️ 部署说明

### 方案一：Render.com（推荐，免费支持 Flask）

1. Fork 本仓库到你的 GitHub
2. 访问 [render.com](https://render.com) → 用 GitHub 登录
3. New → Web Service → 选择仓库
4. 设置：
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python app.py`
   - **Plan**: Free
5. 点击 Deploy，3-5 分钟后上线！

> ⚠️ Render 免费版每月有 750 小时限制，适合个人学习使用。

### 方案二：使用 HuggingFace Spaces（免费 GPU）

1. 创建 [HuggingFace Space](https://huggingface.co/new-space)
2. 选择 **Docker** 模板
3. 上传所有文件
4. 在 `README.md` 顶部添加 metadata：
```yaml
---
title: A股量化工具
emoji: 📊
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
---
```
5. 等待构建完成，获得公开 URL

### 方案三：阿里云/腾讯云轻量应用服务器

```bash
# SSH 登录服务器
cd /www
git clone https://github.com/YOUR_USERNAME/quant-dashboard.git
cd quant-dashboard
pip install -r requirements.txt
nohup python app.py &   # 后台运行
```

---

## ⚠️ 免责声明

- 本工具**仅供学习参考**，不构成任何投资建议
- 工具不会执行任何实际交易操作
- 数据来源为东方财富等公开接口，可能存在延迟
- 投资有风险，入市需谨慎

---

## 📝 自选股配置

修改 `app.py` 中的 `DEFAULT_STOCKS` 列表即可添加/删除股票：

```python
DEFAULT_STOCKS = [
    {"code": "002119", "market": "sz", "name": "康强电子"},
    {"code": "600602", "market": "sh", "name": "云赛智联"},
    {"code": "600629", "market": "sh", "name": "华建集团"},
    # 添加更多股票...
]
```

---

**祝你投资顺利！🤑**
