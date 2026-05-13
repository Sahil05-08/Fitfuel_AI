# 🥗 FitFuel AI — Fitness Meal Planner

> **Your personal AI-powered fitness meal planning assistant.**  
> Tell it what's in your fridge. It builds you a recipe — optimized for your goal.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Railway-blueviolet?style=for-the-badge&logo=railway)](https://fitnessai-production-5f00.up.railway.app)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-Backend-000000?style=for-the-badge&logo=flask)](https://flask.palletsprojects.com)
[![Groq](https://img.shields.io/badge/Groq-LLaMA%2070B-F54B27?style=for-the-badge)](https://groq.com)

---

## 🌐 Live Deployment

```
https://fitnessai-production-5f00.up.railway.app
```

Hosted on **Railway** — no setup needed, open and start chatting.

---

## ✨ What It Does

FitFuel AI is a conversational fitness meal planner. You chat naturally, tell it your ingredients, and it:

- 🍳 Generates a **fitness-optimized recipe** with full macro breakdown
- 🎯 Tailors everything to your **fitness goal** (fat loss, muscle gain, endurance, maintenance)
- 🥦 Respects your **diet type** (vegan, vegetarian, keto, gluten-free, dairy-free)
- 📊 Calculates **BMR / TDEE / daily macro targets**
- 💊 Guides you on **supplement timing and dosage**
- 🔄 Suggests **ingredient substitutions**
- 🛒 Generates a **weekly grocery list**
- 💧 Calculates **daily water intake**
- 📸 Detects ingredients from a **fridge photo** (AI vision)
- 🔊 Reads recipes aloud via **text-to-speech**
- 🧠 Remembers your preferences across the session with **ChromaDB**

---

## 🖼️ App Preview

```
You:  "I have chicken and rice"
Bot:  "What's your fitness goal? fat loss / muscle gain / endurance / maintenance"

You:  "fat loss"
Bot:  "What's your diet type? vegetarian / vegan / non-vegetarian"

You:  "non-vegetarian"

Bot:  🍽️ Grilled Chicken & Brown Rice Bowl — 🔥 Fat Loss
      ─────────────────────────────────────────────────
      🧬 Macros Per Serving:
        • Calories: ~320 kcal
        • Protein:  ~38g
        • Carbs:    ~22g
        • Fat:      ~8g

      📝 Steps:
        1. Season chicken with salt, pepper, lemon...
        2. Grill on medium heat for 6–8 min per side...
        3. Serve with steamed rice and greens.

      🏆 Tip: Keep calories under 500/serving for fat loss.
```

---

## 🚀 Features at a Glance

| Feature | How to Use |
|---|---|
| 🍳 Recipe Generator | *"I have eggs and oats"* |
| 🔍 Macro Lookup | *"macros of salmon"* |
| 🔄 Ingredient Swap | *"substitute for paneer"* |
| 🛒 Grocery List | *"give me a shopping list"* |
| 💊 Supplement Guide | *"when should I take creatine"* |
| 💧 Hydration Target | *"water intake for 80kg"* |
| 🗓️ Meal Plan | *"give me a 3-day meal plan"* |
| 🎨 Recipe Variations | *"make it spicy"* / *"make it Indian style"* |
| 📸 Fridge Scan | Upload a photo → auto-detect ingredients |
| 📊 Fitness Profile | Enter weight, height, age → get TDEE + macros |

---

## 🏗️ Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.10+, Flask |
| **AI / LLM** | Groq API — LLaMA 3.3 70B Versatile |
| **Vision** | Meta LLaMA 4 Scout (fridge scan) |
| **Memory** | ChromaDB (persistent vector store) |
| **Spell Check** | RapidFuzz (fuzzy ingredient matching) |
| **Text-to-Speech** | edge-tts (Microsoft Neural TTS) |
| **Image Processing** | Pillow (PIL) |
| **Hosting** | Railway |
| **Frontend** | HTML / CSS / JS (served via Flask Jinja2) |

---

## ⚙️ Local Setup

### 1. Clone the Repository

```bash
git clone https://github.com/Sahil05-08/Fitfuel_AI
cd fitfuel-ai
```

### 2. Create a Virtual Environment

```bash
python -m venv venv
source venv/bin/activate        # macOS/Linux
venv\Scripts\activate           # Windows
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Set Up Environment Variables

Create a `.env` file in the root directory:

```env
GROQ_API_KEY=your_groq_api_key_here
```

Get your free API key at [console.groq.com](https://console.groq.com)

### 5. Run the App

```bash
python app.py
```

Open your browser at `http://localhost:5000`

---

## 📦 Requirements

```txt
flask
groq
python-dotenv
chromadb
rapidfuzz
edge-tts
Pillow
```

---

## 🌐 API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/chat` | Main chat — send message, receive reply |
| `POST` | `/api/profile` | Calculate BMR / TDEE / macros |
| `POST` | `/api/mealplan` | Generate a multi-day meal plan |
| `POST` | `/api/scan` | Upload fridge image → detect ingredients |
| `GET` | `/api/macros?ingredient=chicken` | Nutrition lookup |
| `GET` | `/api/substitute?ingredient=paneer` | Ingredient substitution |
| `GET` | `/api/shopping?goal=fat_loss&days=7` | Weekly grocery list |
| `GET` | `/api/supplement?name=creatine` | Supplement timing guide |
| `GET` | `/api/water?weight=75&activity=moderate` | Water intake calculator |
| `POST` | `/api/reset` | Clear session state |

### Example Chat Request

```bash
curl -X POST https://fitnessai-production-5f00.up.railway.app/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I have chicken and rice", "history": []}'
```

### Example Response

```json
{
  "reply": "Nice, I can work with chicken, rice! 🥘\n\nWhat's your fitness goal?...",
  "history": [...],
  "audio": "<base64_mp3>",
  "corrections": [{"from": "chiken", "to": "chicken"}]
}
```

---

## 🧠 How the Chat Flow Works

```
User Message
     │
     ▼
Spell Correction (RapidFuzz)
     │
     ▼
Pending State Check
  ├── awaiting_goal?  → Ask for goal → Wait
  ├── awaiting_diet?  → Ask for diet → Wait
  └── None           → Continue ↓
     │
     ▼
Intent Detection
  ├── macro_lookup    → Nutrition table
  ├── substitution    → Swap suggestions
  ├── supplement      → Timing guide
  ├── water_intake    → Hydration target
  ├── meal_plan       → Multi-day plan
  ├── recipe          → Start goal/diet flow → Generate recipe
  └── chat            → Groq conversational fallback
```

---

## 🎯 Fitness Goals & Macro Splits

| Goal | Protein | Carbs | Fat | Calorie Adjust |
|---|---|---|---|---|
| 🔥 Fat Loss | 45% | 25% | 30% | −400 kcal |
| 🏋️ Muscle Gain | 40% | 40% | 20% | +300 kcal |
| 🏃 Endurance | 25% | 55% | 20% | +100 kcal |
| ⚖️ Maintenance | 30% | 40% | 30% | 0 kcal |

---

## 🗂️ Project Structure

```
fitfuel-ai/
├── app.py                  # Main Flask backend (all logic)
├── templates/
│   └── index.html          # Frontend chat UI
├── static/                 # CSS, JS, images
├── fitfuel_memory/         # ChromaDB persistent store
├── .env                    # API keys (not committed)
├── requirements.txt
└── README.md
```

---

## 🔒 Environment Variables

| Variable | Description | Required |
|---|---|---|
| `GROQ_API_KEY` | Groq API key for LLaMA inference | ✅ Yes |

---

## 🚢 Deploy to Railway

1. Fork this repo
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub**
3. Select your forked repo
4. Add environment variable: `GROQ_API_KEY = your_key`
5. Railway auto-detects Flask and deploys 🎉

---

## 💡 Usage Tips

- Just type ingredients naturally: *"eggs, oats, banana"* or *"I only have chicken"*
- Say your goal once — FitFuel remembers it for the session
- Type *"make it spicy"* or *"Indian style"* to get a variation of your last recipe
- Upload a fridge photo on the Scan tab to auto-detect ingredients
- Fill out the Profile tab once to get personalized calorie and macro targets

---

## 🤝 Contributing

Contributions are welcome!

```bash
# Fork → clone → create branch
git checkout -b feature/your-feature

# Make changes, then
git commit -m "Add: your feature"
git push origin feature/your-feature

# Open a Pull Request
```

---

## 👨‍💻 Author

**Sahil Suryawanshi**  
Built with 💪 and a passion for fitness + AI.

---

## 📄 License

MIT License — free to use, modify, and distribute.

---

<div align="center">

**⭐ Star this repo if FitFuel helped you eat better!**

[🌐 Live App](https://fitnessai-production-5f00.up.railway.app) · [🐛 Report Bug](https://github.com/your-username/fitfuel-ai/issues) · [✨ Request Feature](https://github.com/your-username/fitfuel-ai/issues)

</div>