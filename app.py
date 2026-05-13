"""
FitFuel AI — Fitness Meal Planner
Flask backend — by Sahil Suryawanshi

Changes from original:
  1. Conversational goal/diet collection — no popup buttons.
     Backend asks "type fat loss / muscle gain…" and waits for the reply.
  2. Spelling corrections returned to frontend as {"from": x, "to": y} list.
  3. Pending-state machine: "awaiting_goal" / "awaiting_diet" tracks the
     two-step onboarding before generating the first recipe.
  4. General "chat" fallback routed to Groq for richer conversational replies.
"""

import os
import re
import asyncio
import tempfile
import base64
from rapidfuzz import process
from groq import Groq
from dotenv import load_dotenv
import chromadb
from datetime import datetime
import edge_tts
from PIL import Image
from flask import Flask, request, jsonify, render_template

# ==============================
# 🔑 SETUP
# ==============================
load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

app = Flask(__name__)
app.secret_key = "fitfuel-secret-key"

# ==============================
# 🏋️ FITNESS GOAL PROFILES
# ==============================
FITNESS_PROFILES = {
    "muscle_gain": {
        "label":       "🏋️ Muscle Gain",
        "calorie_mod": +300,
        "protein_pct": 0.40,
        "carb_pct":    0.40,
        "fat_pct":     0.20,
        "prompt_note": (
            "HIGH PROTEIN is critical. Prioritize lean protein sources. "
            "Include complex carbs for energy. Moderate healthy fats. "
            "Aim for 2g protein per kg bodyweight. Suggest post-workout meals."
        ),
        "color": "#3b82f6",
    },
    "fat_loss": {
        "label":       "🔥 Fat Loss",
        "calorie_mod": -400,
        "protein_pct": 0.45,
        "carb_pct":    0.25,
        "fat_pct":     0.30,
        "prompt_note": (
            "HIGH PROTEIN to preserve muscle. LOW carb, LOW calorie. "
            "Use lean meats, leafy greens, fiber-rich vegetables. "
            "Avoid fried, sugary, or heavy-fat preparations. "
            "Prefer steaming, boiling, grilling. Keep calories under 500/serving."
        ),
        "color": "#ef4444",
    },
    "endurance": {
        "label":       "🏃 Endurance",
        "calorie_mod": +100,
        "protein_pct": 0.25,
        "carb_pct":    0.55,
        "fat_pct":     0.20,
        "prompt_note": (
            "HIGH CARBS for sustained energy. Include complex carbs like oats, "
            "rice, sweet potato. Moderate protein for recovery. "
            "Suggest pre-run/pre-workout and post-run meals."
        ),
        "color": "#f59e0b",
    },
    "maintenance": {
        "label":       "⚖️ Maintenance",
        "calorie_mod": 0,
        "protein_pct": 0.30,
        "carb_pct":    0.40,
        "fat_pct":     0.30,
        "prompt_note": (
            "BALANCED macros. Equal focus on protein, carbs, and healthy fats. "
            "Whole foods preferred. Nutrient-dense meals."
        ),
        "color": "#22c55e",
    },
}

MEAL_TIMING = {
    "pre_workout":  "🏋️ Pre-Workout (1–2 hrs before): Fast carbs + moderate protein. Low fat.",
    "post_workout": "💪 Post-Workout (within 45 min): Fast protein + simple carbs. Minimal fat.",
    "breakfast":    "🌅 Breakfast: Balanced protein + complex carbs. Sets energy for the day.",
    "lunch":        "☀️ Lunch: High protein + fiber. Largest meal of the day.",
    "dinner":       "🌙 Dinner: High protein + low carb. Light and easy to digest.",
    "snack":        "🍎 Snack: Protein-rich, low sugar. Keeps metabolism active.",
}

# ==============================
# 🎨 WELCOME MESSAGE
# ==============================
WELCOME_MSG = """## 💪 Hey! Welcome to FitFuel AI

I'm your personal **fitness meal planner** — just chat with me naturally!

**Tell me what you have:**
- *"I have chicken and rice"*
- *"oats, banana, milk"*
- *"I only have eggs"*

I'll ask about your **goal** and **diet type**, then give you a full recipe with macros 🥗

**Or try these quick questions:**
- *"macros of salmon"* → nutrition lookup
- *"substitute for paneer"* → ingredient swaps
- *"when should I take creatine"* → supplement guide
- *"water intake for 80kg"* → hydration target"""

# ==============================
# 🧠 PERSISTENT MEMORY (ChromaDB)
# ==============================
chroma_client = None
memory_db = None

def get_memory_db():
    global chroma_client, memory_db
    if memory_db is None:
        try:
            chroma_client = chromadb.PersistentClient(path="./fitfuel_memory")
            memory_db = chroma_client.get_or_create_collection("fitfuel_user")
        except Exception as e:
            print(f"[ChromaDB] Init error: {e}")
    return memory_db

def save_memory(user_id, info):
    try:
        db = get_memory_db()
        if db:
            db.add(
                documents=[info],
                ids=[f"{user_id}_{datetime.now().timestamp()}"]
            )
    except Exception as e:
        print(f"[Memory] Save error: {e}")

def get_memory(user_id, query):
    try:
        db = get_memory_db()
        if db:
            results = db.query(query_texts=[query], n_results=3)
            return results["documents"][0] if results["documents"] else []
    except Exception as e:
        print(f"[Memory] Recall error: {e}")
    return []

# ==============================
# 🥗 NUTRITION DATABASE
# ==============================
NUTRITION_DB = {
    "chicken":        {"calories": 165, "protein": 31.0, "carbs":  0.0, "fat":  3.6, "fiber": 0.0},
    "chicken breast": {"calories": 165, "protein": 31.0, "carbs":  0.0, "fat":  3.6, "fiber": 0.0},
    "egg":            {"calories": 155, "protein": 13.0, "carbs":  1.1, "fat": 11.0, "fiber": 0.0},
    "egg white":      {"calories":  52, "protein": 11.0, "carbs":  0.7, "fat":  0.2, "fiber": 0.0},
    "tuna":           {"calories": 132, "protein": 29.0, "carbs":  0.0, "fat":  1.0, "fiber": 0.0},
    "salmon":         {"calories": 208, "protein": 20.0, "carbs":  0.0, "fat": 13.0, "fiber": 0.0},
    "fish":           {"calories": 180, "protein": 22.0, "carbs":  0.0, "fat":  8.0, "fiber": 0.0},
    "shrimp":         {"calories":  99, "protein": 24.0, "carbs":  0.2, "fat":  0.3, "fiber": 0.0},
    "paneer":         {"calories": 265, "protein": 18.0, "carbs":  1.2, "fat": 21.0, "fiber": 0.0},
    "tofu":           {"calories":  76, "protein":  8.0, "carbs":  1.9, "fat":  4.8, "fiber": 0.3},
    "turkey":         {"calories": 189, "protein": 29.0, "carbs":  0.0, "fat":  7.4, "fiber": 0.0},
    "greek yogurt":   {"calories":  59, "protein": 10.0, "carbs":  3.6, "fat":  0.4, "fiber": 0.0},
    "cottage cheese": {"calories":  98, "protein": 11.0, "carbs":  3.4, "fat":  4.3, "fiber": 0.0},
    "whey protein":   {"calories": 400, "protein": 80.0, "carbs": 10.0, "fat":  5.0, "fiber": 0.0},
    "oats":           {"calories": 389, "protein": 17.0, "carbs": 66.0, "fat":  7.0, "fiber": 10.5},
    "brown rice":     {"calories": 216, "protein":  5.0, "carbs": 45.0, "fat":  1.8, "fiber":  3.5},
    "rice":           {"calories": 206, "protein":  4.3, "carbs": 45.0, "fat":  0.4, "fiber":  0.6},
    "sweet potato":   {"calories":  86, "protein":  1.6, "carbs": 20.0, "fat":  0.1, "fiber":  3.0},
    "quinoa":         {"calories": 222, "protein":  8.1, "carbs": 39.0, "fat":  3.6, "fiber":  5.2},
    "lentil":         {"calories": 116, "protein":  9.0, "carbs": 20.0, "fat":  0.4, "fiber":  7.9},
    "dal":            {"calories": 116, "protein":  9.0, "carbs": 20.0, "fat":  0.4, "fiber":  7.9},
    "chickpea":       {"calories": 164, "protein":  9.0, "carbs": 27.0, "fat":  2.6, "fiber":  7.6},
    "banana":         {"calories":  89, "protein":  1.1, "carbs": 23.0, "fat":  0.3, "fiber":  2.6},
    "potato":         {"calories":  77, "protein":  2.0, "carbs": 17.0, "fat":  0.1, "fiber":  2.2},
    "bread":          {"calories": 265, "protein":  9.0, "carbs": 49.0, "fat":  3.3, "fiber":  2.7},
    "pasta":          {"calories": 131, "protein":  5.0, "carbs": 25.0, "fat":  1.1, "fiber":  1.8},
    "wheat":          {"calories": 340, "protein": 13.0, "carbs": 72.0, "fat":  2.5, "fiber": 12.2},
    "spinach":        {"calories":  23, "protein":  2.9, "carbs":  3.6, "fat":  0.4, "fiber":  2.2},
    "broccoli":       {"calories":  34, "protein":  2.8, "carbs":  7.0, "fat":  0.4, "fiber":  2.6},
    "kale":           {"calories":  35, "protein":  2.9, "carbs":  4.4, "fat":  0.5, "fiber":  4.1},
    "tomato":         {"calories":  18, "protein":  0.9, "carbs":  3.9, "fat":  0.2, "fiber":  1.2},
    "onion":          {"calories":  40, "protein":  1.1, "carbs":  9.0, "fat":  0.1, "fiber":  1.7},
    "carrot":         {"calories":  41, "protein":  0.9, "carbs": 10.0, "fat":  0.2, "fiber":  2.8},
    "capsicum":       {"calories":  31, "protein":  1.0, "carbs":  6.0, "fat":  0.3, "fiber":  2.1},
    "cucumber":       {"calories":  16, "protein":  0.7, "carbs":  3.6, "fat":  0.1, "fiber":  0.5},
    "mushroom":       {"calories":  22, "protein":  3.1, "carbs":  3.3, "fat":  0.3, "fiber":  1.0},
    "cauliflower":    {"calories":  25, "protein":  1.9, "carbs":  5.0, "fat":  0.3, "fiber":  2.0},
    "cabbage":        {"calories":  25, "protein":  1.3, "carbs":  6.0, "fat":  0.1, "fiber":  2.5},
    "peas":           {"calories":  81, "protein":  5.4, "carbs": 14.0, "fat":  0.4, "fiber":  5.1},
    "milk":           {"calories":  61, "protein":  3.2, "carbs":  4.8, "fat":  3.3, "fiber": 0.0},
    "butter":         {"calories": 717, "protein":  0.9, "carbs":  0.1, "fat": 81.0, "fiber": 0.0},
    "cheese":         {"calories": 402, "protein": 25.0, "carbs":  1.3, "fat": 33.0, "fiber": 0.0},
    "almond":         {"calories": 579, "protein": 21.0, "carbs": 22.0, "fat": 50.0, "fiber": 12.5},
    "peanut":         {"calories": 567, "protein": 26.0, "carbs": 16.0, "fat": 49.0, "fiber":  8.5},
    "avocado":        {"calories": 160, "protein":  2.0, "carbs":  9.0, "fat": 15.0, "fiber":  6.7},
    "olive oil":      {"calories": 884, "protein":  0.0, "carbs":  0.0, "fat":100.0, "fiber": 0.0},
    "apple":          {"calories":  52, "protein":  0.3, "carbs": 14.0, "fat":  0.2, "fiber":  2.4},
    "orange":         {"calories":  47, "protein":  0.9, "carbs": 12.0, "fat":  0.1, "fiber":  2.4},
    "mango":          {"calories":  60, "protein":  0.8, "carbs": 15.0, "fat":  0.4, "fiber":  1.6},
    "strawberry":     {"calories":  32, "protein":  0.7, "carbs":  7.7, "fat":  0.3, "fiber":  2.0},
    "blueberry":      {"calories":  57, "protein":  0.7, "carbs": 14.0, "fat":  0.3, "fiber":  2.4},
    "chia seeds":     {"calories": 486, "protein": 17.0, "carbs": 42.0, "fat": 31.0, "fiber": 34.4},
    "flax seeds":     {"calories": 534, "protein": 18.0, "carbs": 29.0, "fat": 42.0, "fiber": 27.3},
}

FITNESS_INGREDIENTS = list(NUTRITION_DB.keys()) + [
    "ginger", "garlic", "lemon", "lime", "coriander", "turmeric",
    "black pepper", "cumin", "cinnamon", "salt", "oil", "water",
    "soy sauce", "vinegar", "honey", "coconut oil", "mustard",
    "whey", "protein powder", "rajma", "moong dal", "urad dal",
    "toor dal", "chana dal", "soya chunks", "kidney beans",
    "black beans", "edamame", "tempeh", "mutton", "beef", "pork",
]

# ==============================
# 💊 SUPPLEMENT DATABASE
# ==============================
SUPPLEMENT_GUIDE = {
    "creatine": {
        "when": "Post-workout or any time of day (consistency > timing)",
        "dose": "3–5g daily",
        "benefit": "Increases strength, power output, and muscle volume",
        "tip": "Take with carbs post-workout for better absorption. Loading phase optional.",
        "goal": ["muscle_gain", "endurance"],
    },
    "whey protein": {
        "when": "Within 30–45 minutes post-workout",
        "dose": "25–35g per serving",
        "benefit": "Fast-digesting protein for muscle repair and growth",
        "tip": "Also great as breakfast or between meals if daily protein is low.",
        "goal": ["muscle_gain", "fat_loss"],
    },
    "bcaa": {
        "when": "During or immediately after workout",
        "dose": "5–10g per serving",
        "benefit": "Reduces muscle breakdown, aids recovery during fasted training",
        "tip": "Useful if training fasted. Less necessary if protein intake is adequate.",
        "goal": ["muscle_gain", "fat_loss", "endurance"],
    },
    "pre workout": {
        "when": "20–30 minutes before training",
        "dose": "1 scoop (per label)",
        "benefit": "Boosts energy, focus, and workout performance",
        "tip": "Avoid after 4 PM if sensitive to caffeine. Cycle off every 6–8 weeks.",
        "goal": ["muscle_gain", "fat_loss", "endurance"],
    },
    "omega 3": {
        "when": "With meals (reduces fish burps)",
        "dose": "1–3g EPA+DHA daily",
        "benefit": "Reduces inflammation, supports heart health and joint recovery",
        "tip": "Especially important if you don't eat fatty fish 2–3x/week.",
        "goal": ["muscle_gain", "fat_loss", "endurance", "maintenance"],
    },
    "vitamin d": {
        "when": "Morning with a fatty meal",
        "dose": "1000–2000 IU daily",
        "benefit": "Supports testosterone, immune function, and bone health",
        "tip": "Most Indians are deficient. Get tested and supplement accordingly.",
        "goal": ["muscle_gain", "fat_loss", "endurance", "maintenance"],
    },
    "magnesium": {
        "when": "Before bed (aids sleep)",
        "dose": "200–400mg as magnesium glycinate",
        "benefit": "Improves sleep quality, reduces muscle cramps, supports recovery",
        "tip": "Best form: magnesium glycinate. Avoid oxide — poor absorption.",
        "goal": ["muscle_gain", "fat_loss", "endurance", "maintenance"],
    },
    "caffeine": {
        "when": "30–45 minutes before workout or morning",
        "dose": "100–200mg",
        "benefit": "Improves endurance, focus, strength output, and fat oxidation",
        "tip": "Black coffee works perfectly. Don't exceed 400mg/day total.",
        "goal": ["fat_loss", "endurance"],
    },
    "casein": {
        "when": "30 minutes before bed",
        "dose": "25–40g",
        "benefit": "Slow-digesting protein that feeds muscles overnight",
        "tip": "Best for muscle gain. Cottage cheese is a whole food alternative.",
        "goal": ["muscle_gain"],
    },
}

# ==============================
# 🔄 INGREDIENT SUBSTITUTION MAP
# ==============================
SUBSTITUTION_MAP = {
    "paneer":       ["tofu (vegan)", "cottage cheese", "chicken breast (non-veg)", "greek yogurt"],
    "chicken":      ["turkey breast", "tofu", "tempeh (vegan)", "fish", "egg white"],
    "chicken breast":["turkey breast", "tofu", "tempeh", "fish"],
    "egg":          ["flax egg (1 tbsp flax + 3 tbsp water)", "chia egg", "tofu scramble (vegan)"],
    "milk":         ["almond milk (vegan)", "oat milk (vegan)", "soy milk", "coconut milk"],
    "butter":       ["coconut oil", "avocado", "olive oil", "greek yogurt (baking)"],
    "cheese":       ["nutritional yeast (vegan)", "tofu (blended)", "cottage cheese"],
    "whey protein": ["plant protein powder (vegan)", "soy protein", "pea protein"],
    "brown rice":   ["quinoa (higher protein)", "cauliflower rice (low carb/keto)", "oats"],
    "rice":         ["quinoa", "cauliflower rice (keto)", "sweet potato"],
    "oats":         ["quinoa flakes", "muesli", "buckwheat (gluten-free)"],
    "bread":        ["sweet potato toast (gluten-free)", "rice cakes", "oat wraps"],
    "pasta":        ["zucchini noodles (keto)", "chickpea pasta (high protein)", "quinoa pasta"],
    "sugar":        ["honey", "dates", "stevia", "banana (in baking)"],
    "mayonnaise":   ["greek yogurt", "avocado", "hummus"],
    "soy sauce":    ["coconut aminos (gluten-free)", "tamari"],
    "salmon":       ["tuna", "mackerel", "sardine", "chicken breast"],
    "beef":         ["bison", "turkey mince", "lentil (vegan)", "tofu"],
    "peanut":       ["almond", "cashew", "sunflower seeds (nut-free)"],
    "almond":       ["cashew", "walnut", "sunflower seeds", "pumpkin seeds"],
}

# ==============================
# 🥦 DIETARY RESTRICTION FILTERS
# ==============================
DIETARY_FILTERS = {
    "vegan": {
        "exclude": ["chicken", "chicken breast", "egg", "egg white", "fish", "salmon", "tuna",
                    "shrimp", "turkey", "beef", "pork", "mutton", "milk", "butter", "cheese",
                    "greek yogurt", "cottage cheese", "whey protein", "paneer", "casein"],
        "prompt_note": "This is a VEGAN recipe. Use ONLY plant-based ingredients. No meat, dairy, or eggs.",
    },
    "vegetarian": {
        "exclude": ["chicken", "chicken breast", "fish", "salmon", "tuna", "shrimp",
                    "turkey", "beef", "pork", "mutton"],
        "prompt_note": "This is a VEGETARIAN recipe. No meat or fish. Eggs and dairy are allowed.",
    },
    "keto": {
        "exclude": ["rice", "brown rice", "oats", "bread", "pasta", "wheat", "potato",
                    "sweet potato", "banana", "mango", "chickpea", "lentil", "dal",
                    "quinoa", "honey", "sugar"],
        "prompt_note": "This is a KETO recipe. Keep carbs under 20g total. High fat, moderate protein.",
    },
    "gluten_free": {
        "exclude": ["bread", "pasta", "wheat", "oats"],
        "prompt_note": "This is a GLUTEN-FREE recipe. No wheat, bread, pasta, or regular oats.",
    },
    "dairy_free": {
        "exclude": ["milk", "butter", "cheese", "greek yogurt", "cottage cheese",
                    "whey protein", "casein", "paneer"],
        "prompt_note": "This is a DAIRY-FREE recipe. No milk, cheese, yogurt, or dairy-based protein.",
    },
}

# ==============================
# 🧮 BMR / TDEE
# ==============================
def calculate_bmr(weight_kg, height_cm, age, gender):
    if gender.lower() in ["male", "m"]:
        return 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
    return 10 * weight_kg + 6.25 * height_cm - 5 * age - 161

ACTIVITY_MULTIPLIERS = {
    "sedentary": 1.2, "light": 1.375, "moderate": 1.55,
    "active": 1.725, "very_active": 1.9,
}

def calculate_tdee(bmr, activity_level):
    return round(bmr * ACTIVITY_MULTIPLIERS.get(activity_level, 1.55))

def calculate_macros(tdee, goal):
    profile = FITNESS_PROFILES.get(goal, FITNESS_PROFILES["maintenance"])
    target = tdee + profile["calorie_mod"]
    return {
        "calories": round(target),
        "protein":  round(target * profile["protein_pct"] / 4),
        "carbs":    round(target * profile["carb_pct"] / 4),
        "fat":      round(target * profile["fat_pct"] / 9),
    }

def calculate_water_intake(weight_kg, activity_level="moderate"):
    base = weight_kg * 35
    activity_bonus = {
        "sedentary": 0, "light": 250, "moderate": 500,
        "active": 750, "very_active": 1000,
    }
    total_ml = base + activity_bonus.get(activity_level, 500)
    return {
        "ml": round(total_ml),
        "liters": round(total_ml / 1000, 1),
        "glasses": round(total_ml / 250),
    }

def generate_fitness_profile_summary(weight, height, age, gender, activity, goal):
    try:
        w, h, a = float(weight), float(height), int(age)
        bmr    = calculate_bmr(w, h, a, gender)
        tdee   = calculate_tdee(bmr, activity)
        macros = calculate_macros(tdee, goal)
        water  = calculate_water_intake(w, activity)
        profile = FITNESS_PROFILES.get(goal, FITNESS_PROFILES["maintenance"])
        return f"""## 📊 Your Fitness Profile

| Metric | Value |
|--------|-------|
| ⚖️ Weight | {w} kg |
| 📏 Height | {h} cm |
| 🎂 Age | {a} yrs |
| 🏃 Activity | {activity.replace('_',' ').title()} |
| 🎯 Goal | {profile['label']} |

### 🔥 Energy Needs
- **BMR:** {round(bmr)} kcal/day
- **TDEE:** {tdee} kcal/day
- **Target:** {macros['calories']} kcal/day

### 🧬 Daily Macro Targets
| Macro | Grams/Day | % |
|-------|-----------|---|
| 💪 Protein | **{macros['protein']}g** | {round(profile['protein_pct']*100)}% |
| 🌾 Carbs | **{macros['carbs']}g** | {round(profile['carb_pct']*100)}% |
| 🧈 Fat | **{macros['fat']}g** | {round(profile['fat_pct']*100)}% |

### 💧 Daily Water Intake
- **Target:** {water['liters']}L ({water['ml']}ml)
- **Glasses:** ~{water['glasses']} glasses (250ml each)

💡 Tip: Spread protein across 4–5 meals (~{round(macros['protein']/5)}g per meal)"""
    except Exception as e:
        return f"⚠️ Error: {e}"

# ==============================
# 🥗 NUTRITION CALC
# ==============================
def calculate_nutrition(ingredients, servings=2):
    try:
        total = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0}
        found = []
        for ing in ingredients:
            if ing.lower() in NUTRITION_DB:
                n = NUTRITION_DB[ing.lower()]
                for k in total:
                    total[k] += n.get(k, 0)
                found.append(ing)
        if not found:
            return ""
        if servings > 0:
            for k in total:
                total[k] = round(total[k] / servings, 1)
        prot_ratio = (total["protein"] * 4) / max(total["calories"], 1)
        score = "🟢 Excellent" if prot_ratio >= 0.35 else ("🟡 Good" if prot_ratio >= 0.25 else "🟠 Moderate")
        return f"""
### 🧬 Nutrition Per Serving
| Nutrient | Amount |
|----------|--------|
| 🔥 Calories | **{total['calories']} kcal** |
| 💪 Protein | **{total['protein']}g** |
| 🌾 Carbs | {total['carbs']}g |
| 🧈 Fat | {total['fat']}g |
| 🌿 Fiber | {total['fiber']}g |

**Fitness Score:** {score}"""
    except:
        return ""

def quick_macro_lookup(ingredient_name):
    name = ingredient_name.lower().strip()
    if name in NUTRITION_DB:
        n = NUTRITION_DB[name]
        prot_ratio = (n["protein"] * 4) / max(n["calories"], 1)
        score = "🟢 Excellent" if prot_ratio >= 0.35 else ("🟡 Good" if prot_ratio >= 0.25 else "🟠 Moderate")
        return f"""## 🔍 Macros: {ingredient_name.title()} (per 100g)

| Nutrient | Amount |
|----------|--------|
| 🔥 Calories | **{n['calories']} kcal** |
| 💪 Protein | **{n['protein']}g** |
| 🌾 Carbs | {n['carbs']}g |
| 🧈 Fat | {n['fat']}g |
| 🌿 Fiber | {n['fiber']}g |

**Fitness Score:** {score}
💡 Protein density: {round(prot_ratio * 100)}% of calories from protein"""

    match = process.extractOne(name, list(NUTRITION_DB.keys()), score_cutoff=75)
    if match:
        return quick_macro_lookup(match[0])

    return f"❌ '{ingredient_name}' not found. Try: 'chicken breast', 'oats', or 'salmon'."

def get_cooking_metrics(ingredients):
    COOK_TIMES = {
        "chicken": 25, "fish": 15, "shrimp": 8, "egg": 7, "tofu": 10,
        "rice": 20, "oats": 5, "lentil": 30, "dal": 30, "quinoa": 18,
        "sweet potato": 20, "potato": 15, "broccoli": 8, "spinach": 4,
    }
    max_time = max((COOK_TIMES.get(i.lower(), 5) for i in ingredients), default=5) + 5
    count = len(ingredients)
    diff = "⭐ Easy" if count <= 2 else ("⭐⭐ Moderate" if count <= 5 else "⭐⭐⭐ Advanced")
    return f"⏱️ Cook Time: ~{max_time} min | Difficulty: {diff}"

# ==============================
# 🔤 INPUT NORMALIZATION
# ==============================
FITNESS_SLANG = {
    r"\bprotein\s*shake\b": "whey protein", r"\bwhey\b": "whey protein",
    r"\bsweet\s*potato\b": "sweet potato", r"\bchicken\s*breast\b": "chicken breast",
    r"\begg\s*whites?\b": "egg white", r"\boat(s|meal)?\b": "oats",
    r"\bbrown\s*rice\b": "brown rice", r"\bgreek\s*yogurt\b": "greek yogurt",
    r"\bcottage\s*cheese\b": "cottage cheese", r"\baloo\b": "potato",
    r"\bpalak\b": "spinach", r"\bpyaaz\b": "onion", r"\btamatar\b": "tomato",
    r"\bchana\b": "chickpea", r"\bmoong\b": "lentil", r"\bsoya\b": "tofu",
    r"\bbuild\s*muscle\b": "muscle gain", r"\blose\s*weight\b": "fat loss",
    r"\blose\s*fat\b": "fat loss", r"\bbulk(ing)?\b": "muscle gain",
    r"\bcut(ting)?\b": "fat loss", r"\bshred(ding)?\b": "fat loss",
    r"\bmaintain\b": "maintenance", r"\brun(ning)?\b": "endurance",
    r"\bcardio\b": "endurance",
    r"\bweight\s*gain\b": "muscle gain",
    r"\bput\s*on\s*weight\b": "muscle gain",
}

# ==============================
# 🔤 SKIP WORDS (shared)
# ==============================
SKIP_WORDS = {
    "i","a","an","the","have","has","and","or","not","just","want","make",
    "me","my","is","it","to","in","on","at","of","for","with","do","will",
    "would","hi","hello","hey","please","can","you","get","also","add",
    "too","plus","got","only","quick","fast","post","pre","workout","gym",
    "spicy","hot","indian","chinese","mexican","simple","easy","vegan",
    "make","style","day","week","meal","plan",
}

INTENT_SKIP_WORDS = {
    "vegetarian", "non", "food", "eat", "eating", "want", "lose", "gain",
    "build", "maintain", "muscle", "weight", "fat", "endurance", "goal",
    "diet", "type", "like", "need", "give", "show", "help", "tell", "use",
    "used", "using", "am", "are", "been", "was", "were",
    "non-vegetarian", "omnivore", "meateater", "plant", "based", "animal",
}

def normalize_fitness_input(text):
    text = text.lower().strip()
    for pattern, replacement in FITNESS_SLANG.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()

def fix_spelling(text):
    combined_skip = SKIP_WORDS | INTENT_SKIP_WORDS
    corrected = []
    for word in text.lower().split():
        if word in combined_skip or len(word) <= 2:
            corrected.append(word)
            continue
        match = process.extractOne(word, FITNESS_INGREDIENTS, score_cutoff=82)
        corrected.append(match[0] if match and match[0] != word else word)
    return " ".join(corrected)

def compute_corrections(original, fixed):
    """Return list of {"from": x, "to": y} dicts showing spelling fixes made."""
    orig_words = original.lower().split()
    fixed_words = fixed.lower().split()
    corrections = []
    combined_skip = SKIP_WORDS | INTENT_SKIP_WORDS
    for o, f in zip(orig_words, fixed_words):
        if o != f and len(o) > 3 and o not in combined_skip:
            corrections.append({"from": o, "to": f})
    return corrections

# ==============================
# 🎯 GOAL / DIET EXTRACTORS
# ==============================
def extract_goal_from_text(text):
    """Extract fitness goal from free-text user reply."""
    t = text.lower()
    if any(k in t for k in ['fat loss', 'lose fat', 'lose weight', 'cut', 'shred',
                              'slim', 'lean', 'weight loss', 'burn fat', 'drop weight']):
        return 'fat_loss'
    if any(k in t for k in ['muscle', 'bulk', 'gain muscle', 'build muscle', 'mass',
                              'strength', 'weight gain', 'gain weight', 'build', 'put on']):
        return 'muscle_gain'
    if any(k in t for k in ['endurance', 'cardio', 'run', 'marathon', 'stamina',
                              'energy', 'running', 'cycling', 'triathlon']):
        return 'endurance'
    if any(k in t for k in ['maintain', 'maintenance', 'balance', 'balanced', 'stay fit']):
        return 'maintenance'
    # Single-word shortcuts
    t_stripped = t.strip()
    shortcuts = {
        'fat': 'fat_loss', 'fat loss': 'fat_loss', 'lose': 'fat_loss',
        'muscle': 'muscle_gain', 'muscle gain': 'muscle_gain', 'bulk': 'muscle_gain',
        'gain': 'muscle_gain', 'build': 'muscle_gain',
        'endurance': 'endurance', 'cardio': 'endurance', 'run': 'endurance',
        'maintain': 'maintenance', 'maintenance': 'maintenance',
    }
    for kw, goal in shortcuts.items():
        if t_stripped == kw or t_stripped.startswith(kw + ' '):
            return goal
    return None


def extract_diet_from_text(text):
    """
    Extract diet type from free-text reply.
    Returns: 'vegan' | 'vegetarian' | 'non_veg' | False
    False means we couldn't understand — should ask again.
    """
    t = text.lower()
    # Vegan first (subset of vegetarian)
    if any(k in t for k in ['vegan', 'plant-based', 'plant based', 'no animal',
                              'no dairy', 'only plants']):
        return 'vegan'
    # Vegetarian
    if re.search(r'\bvegetarian\b', t) and 'non' not in t:
        return 'vegetarian'
    if re.search(r'\bveg\b', t) and 'non' not in t and 'vegan' not in t:
        return 'vegetarian'
    # Non-vegetarian / omnivore / explicit meat mentions as diet answer
    if any(k in t for k in ['non-veg', 'non veg', 'nonveg', 'non vegetarian',
                              'non-vegetarian', 'omnivore', 'eat everything',
                              'eat all', 'everything', 'meat eater', 'not veg',
                              'not vegetarian', 'nv', 'non veg']):
        return 'non_veg'
    # If they mention a non-veg food as their answer (e.g. "I eat chicken")
    non_veg_foods = ['chicken', 'fish', 'beef', 'pork', 'mutton', 'shrimp',
                     'tuna', 'salmon', 'turkey', 'meat', 'egg']
    if any(food in t for food in non_veg_foods):
        return 'non_veg'
    return False  # Couldn't determine

# ==============================
# 🧠 SESSION STATE
# ==============================
user_state = {}

def get_user_state(user_id):
    if user_id not in user_state:
        user_state[user_id] = {
            "ingredients":          [],
            "goal":                 "fat_loss",
            "goal_set":             False,   # Was goal explicitly chosen by user?
            "diet_set":             False,   # Was diet preference explicitly answered?
            "meal_timing":          "any",
            "servings":             2,
            "last_recipe":          None,
            "profile":              {},
            "dietary":              set(),
            "last_variation":       None,
            "calories_logged_today":0,
            "pending":              None,    # "awaiting_goal" | "awaiting_diet" | None
        }
    return user_state[user_id]

def clear_user_state(user_id):
    if user_id in user_state:
        del user_state[user_id]

def update_state(user_id, message):
    state = get_user_state(user_id)
    text  = message.lower()

    # --- Goal detection ---
    goal_keywords = {
        "muscle_gain": ["muscle", "bulk", "gain", "build", "mass", "strength", "weight gain", "put on weight"],
        "fat_loss":    ["fat loss", "lose fat", "lose weight", "cut", "shred", "slim", "lean", "diet"],
        "endurance":   ["endurance", "cardio", "run", "marathon", "stamina", "energy"],
        "maintenance": ["maintain", "maintenance", "balance", "balanced"],
    }
    for goal, keywords in goal_keywords.items():
        if any(k in text for k in keywords):
            state["goal"] = goal
            state["goal_set"] = True          # Mark as explicitly set
            save_memory(user_id, f"Fitness goal: {goal}")
            break

    # --- Dietary restriction detection ---
    dietary_keywords = {
        "vegan":       ["vegan", "plant based", "plant-based", "no meat", "no dairy", "no eggs"],
        "vegetarian":  ["vegetarian", "no meat", "no non-veg"],
        "keto":        ["keto", "ketogenic", "low carb", "no carbs"],
        "gluten_free": ["gluten free", "gluten-free", "no gluten", "celiac"],
        "dairy_free":  ["dairy free", "dairy-free", "no dairy", "lactose intolerant", "no milk"],
    }
    for diet, keywords in dietary_keywords.items():
        if any(k in text for k in keywords):
            state["dietary"].add(diet)
            state["diet_set"] = True          # Mark as explicitly answered
            save_memory(user_id, f"Dietary restriction: {diet}")

    # Also mark diet as set if user explicitly says non-veg (no restriction needed)
    if any(k in text for k in ['non-veg', 'non veg', 'nonveg', 'non vegetarian',
                                'omnivore', 'eat everything', 'meat eater', 'not vegetarian']):
        state["diet_set"] = True

    # --- Meal timing ---
    timing_keywords = {
        "pre_workout":  ["pre workout", "before gym", "pre-workout", "before training"],
        "post_workout": ["post workout", "after gym", "post-workout", "after training"],
        "breakfast":    ["breakfast", "morning"],
        "lunch":        ["lunch", "midday"],
        "dinner":       ["dinner", "night", "evening"],
        "snack":        ["snack", "between meals"],
    }
    for timing, keywords in timing_keywords.items():
        if any(k in text for k in keywords):
            state["meal_timing"] = timing
            break

    # --- Serving count ---
    m = re.search(r'(\d+)\s*(people|persons?|servings?|members?)', text)
    if m:
        state["servings"] = max(1, min(int(m.group(1)), 20))

    # --- Recipe variation ---
    variations = {
        "spicy":   ["spicy", "hot", "fiery", "masala"],
        "indian":  ["indian", "desi", "tadka", "curry", "masala"],
        "chinese": ["chinese", "stir fry", "stir-fry", "asian"],
        "mexican": ["mexican", "burrito", "taco"],
        "simple":  ["simple", "easy", "quick", "5 minute", "5-minute"],
        "vegan":   ["vegan style", "make it vegan"],
    }
    for var, kws in variations.items():
        if any(k in text for k in kws):
            state["last_variation"] = var
            break

    # --- Ingredient extraction ---
    combined_skip = SKIP_WORDS | INTENT_SKIP_WORDS
    words = re.findall(r'\b\w+\b', text)
    for word in words:
        word_lower = word.lower()
        if word_lower in combined_skip or len(word_lower) <= 2:
            continue
        if word_lower in NUTRITION_DB:
            if word_lower not in state["ingredients"]:
                state["ingredients"].append(word_lower)
            continue
        match = process.extractOne(word_lower, FITNESS_INGREDIENTS, score_cutoff=75)
        if match:
            ing = match[0]
            if ing not in state["ingredients"]:
                state["ingredients"].append(ing)

    return state

# ==============================
# 🛒 SHOPPING LIST GENERATOR
# ==============================
def generate_shopping_list(goal="fat_loss", days=7):
    profile = FITNESS_PROFILES.get(goal, FITNESS_PROFILES["maintenance"])
    SHOPPING_LISTS = {
        "muscle_gain": {
            "proteins":   ["Chicken breast (1.5 kg)", "Eggs (2 dozen)", "Greek yogurt (1 kg)", "Paneer or Tofu (500g)", "Tuna cans (4)", "Whey protein"],
            "carbs":      ["Brown rice (1 kg)", "Oats (1 kg)", "Sweet potato (1 kg)", "Quinoa (500g)", "Whole wheat bread"],
            "fats":       ["Almonds (250g)", "Peanut butter", "Olive oil", "Avocado (4)", "Flax seeds (200g)"],
            "vegetables": ["Broccoli", "Spinach", "Capsicum", "Mushroom", "Kale"],
            "fruits":     ["Banana (1 dozen)", "Apple (6)", "Berries (frozen ok)"],
            "extras":     ["Garlic", "Ginger", "Turmeric", "Black pepper", "Lemon (6)"],
        },
        "fat_loss": {
            "proteins":   ["Chicken breast (1.5 kg)", "Egg whites (1 dozen)", "Greek yogurt (500g)", "Tuna cans (6)", "Tofu (400g)", "Salmon (500g)"],
            "carbs":      ["Oats (500g)", "Sweet potato (500g)", "Quinoa (500g)", "Brown rice (500g)"],
            "fats":       ["Avocado (4)", "Olive oil", "Chia seeds (200g)", "Almonds (150g)"],
            "vegetables": ["Broccoli (1 kg)", "Spinach (500g)", "Cucumber", "Cauliflower", "Cabbage", "Tomato", "Capsicum"],
            "fruits":     ["Apple (6)", "Strawberries", "Orange (6)"],
            "extras":     ["Lemon (6)", "Garlic", "Ginger", "Apple cider vinegar", "Green tea"],
        },
        "endurance": {
            "proteins":   ["Chicken breast (1 kg)", "Eggs (2 dozen)", "Greek yogurt (1 kg)", "Salmon (500g)"],
            "carbs":      ["Oats (1 kg)", "Brown rice (1.5 kg)", "Sweet potato (1.5 kg)", "Banana (2 dozen)", "Quinoa (500g)", "Whole wheat pasta"],
            "fats":       ["Peanut butter", "Olive oil", "Almonds (200g)", "Chia seeds"],
            "vegetables": ["Spinach", "Broccoli", "Carrot", "Beets"],
            "fruits":     ["Banana (2 dozen)", "Orange (1 dozen)", "Mango (4)", "Apple (6)"],
            "extras":     ["Honey", "Garlic", "Turmeric", "Ginger", "Lemon"],
        },
        "maintenance": {
            "proteins":   ["Chicken breast (1 kg)", "Eggs (1 dozen)", "Paneer (400g)", "Tuna cans (3)", "Greek yogurt (500g)"],
            "carbs":      ["Brown rice (1 kg)", "Oats (500g)", "Sweet potato (500g)", "Whole wheat bread"],
            "fats":       ["Olive oil", "Avocado (3)", "Almonds (150g)", "Peanut butter"],
            "vegetables": ["Spinach", "Broccoli", "Tomato", "Onion", "Capsicum", "Cucumber"],
            "fruits":     ["Apple (6)", "Banana (6)", "Orange (6)"],
            "extras":     ["Garlic", "Ginger", "Lemon", "Turmeric", "Black pepper"],
        },
    }
    items = SHOPPING_LISTS.get(goal, SHOPPING_LISTS["maintenance"])
    lines = [f"## 🛒 Weekly Grocery List — {profile['label']}\n_(for {days} days | ~2 people)_\n"]
    emoji_map = {"proteins":"💪","carbs":"🌾","fats":"🥑","vegetables":"🥦","fruits":"🍎","extras":"🧂"}
    for category, items_list in items.items():
        lines.append(f"\n### {emoji_map.get(category,'•')} {category.title()}")
        for item in items_list:
            lines.append(f"- [ ] {item}")
    lines.append(f"\n---\n💡 **Tip:** Buy in bulk, meal-prep on Sundays. Freeze chicken in portion bags.")
    return "\n".join(lines)

# ==============================
# 💊 SUPPLEMENT GUIDE
# ==============================
def get_supplement_guide(query, goal="fat_loss"):
    query_lower = query.lower()
    matched = None
    for supp_name, supp_data in SUPPLEMENT_GUIDE.items():
        if supp_name in query_lower:
            matched = (supp_name, supp_data)
            break
    if matched:
        name, data = matched
        return f"""## 💊 Supplement Guide: {name.title()}

| Detail | Info |
|--------|------|
| ⏰ When to Take | {data['when']} |
| 📏 Dose | {data['dose']} |
| 🎯 Benefit | {data['benefit']} |

💡 **Pro Tip:** {data['tip']}

{'⚠️ Recommended for your goal.' if goal in data.get('goal', []) else '⚠️ May not be highest priority for your current goal.'}"""
    goal_supps = [name for name, data in SUPPLEMENT_GUIDE.items() if goal in data.get("goal", [])]
    lines = [f"## 💊 Top Supplements for {FITNESS_PROFILES.get(goal, {}).get('label', goal)}\n"]
    for s in goal_supps[:4]:
        d = SUPPLEMENT_GUIDE[s]
        lines.append(f"**{s.title()}** — {d['dose']} | {d['when']}")
    lines.append("\nAsk me about a specific one: e.g. *'when should I take creatine'*")
    return "\n".join(lines)

# ==============================
# 💧 WATER INTAKE
# ==============================
def get_water_intake_response(query):
    match = re.search(r'(\d+)\s*kg', query)
    if match:
        weight = int(match.group(1))
        activity = "moderate"
        if any(w in query for w in ["active", "gym", "workout", "athlete"]):
            activity = "active"
        elif any(w in query for w in ["sedentary", "desk", "no exercise"]):
            activity = "sedentary"
        water = calculate_water_intake(weight, activity)
        return f"""## 💧 Daily Water Intake for {weight}kg

| Metric | Amount |
|--------|--------|
| 🥤 Daily Target | **{water['liters']}L ({water['ml']}ml)** |
| 🫗 Glasses (250ml) | **~{water['glasses']} glasses** |
| 🏃 Activity Factor | {activity.title()} |

### ⏰ Hydration Schedule
- **Morning:** 500ml on waking (before coffee)
- **Pre-Workout:** 500ml (1 hour before)
- **During Workout:** 250ml every 20 min
- **Post-Workout:** 500–750ml within 1 hour
- **With Meals:** 250ml per meal

💡 Dark urine, fatigue, or headaches = you need more water."""
    return "Tell me your weight to calculate water intake. Example: *'water intake for 75kg'*"

# ==============================
# 🔄 INGREDIENT SUBSTITUTION
# ==============================
def get_substitution(query):
    query_lower = query.lower()
    matched_ing = None
    for ing in SUBSTITUTION_MAP:
        if ing in query_lower:
            matched_ing = ing
            break
    if not matched_ing:
        match = process.extractOne(query_lower, list(SUBSTITUTION_MAP.keys()), score_cutoff=70)
        if match:
            matched_ing = match[0]
    if matched_ing:
        subs = SUBSTITUTION_MAP[matched_ing]
        lines = [f"## 🔄 Substitutes for: {matched_ing.title()}\n"]
        for i, s in enumerate(subs, 1):
            lines.append(f"{i}. **{s}**")
        lines.append(f"\n💡 Tell me your dietary preference for the best pick!")
        return "\n".join(lines)
    return "I don't have a substitute for that yet. Try: *'substitute for paneer'* or *'replace chicken'*."

# ==============================
# 🤖 RECIPE GENERATION
# ==============================
def build_dietary_note(dietary_restrictions):
    if not dietary_restrictions:
        return ""
    notes = []
    for diet in dietary_restrictions:
        if diet in DIETARY_FILTERS:
            notes.append(DIETARY_FILTERS[diet]["prompt_note"])
    return " | ".join(notes)

def filter_ingredients_by_diet(ingredients, dietary_restrictions):
    if not dietary_restrictions:
        return ingredients
    exclude = set()
    for diet in dietary_restrictions:
        if diet in DIETARY_FILTERS:
            exclude.update(DIETARY_FILTERS[diet]["exclude"])
    filtered = [i for i in ingredients if i.lower() not in exclude]
    return filtered if filtered else ingredients

def generate_fitness_recipe(ingredients, goal="fat_loss", meal_timing="any", servings=2,
                             memories=None, dietary=None, variation=None):
    if not ingredients:
        return None
    dietary = dietary or set()
    filtered_ings = filter_ingredients_by_diet(ingredients, dietary)
    profile      = FITNESS_PROFILES.get(goal, FITNESS_PROFILES["maintenance"])
    timing_note  = MEAL_TIMING.get(meal_timing, "")
    mem_text     = f"\nUser history: {', '.join(memories[:2])}" if memories else ""
    dietary_note = build_dietary_note(dietary)
    ingredient_list = "\n".join(f"  - {i}" for i in filtered_ings)

    single_note = ""
    if len(filtered_ings) == 1:
        single_note = (
            f"\nIMPORTANT: The user provided ONLY ONE ingredient: {filtered_ings[0]}. "
            "Build a complete named fitness dish around it. "
            "Use pantry staples (salt, pepper, olive oil, lemon, garlic, ginger, spices, water). "
            "Follow the EXACT format below."
        )

    variation_note = ""
    if variation:
        variation_notes = {
            "spicy":   "Make the dish SPICY with chili, pepper, cayenne, or chili flakes.",
            "indian":  "Make it INDIAN STYLE with cumin, turmeric, coriander, garam masala, and a tadka.",
            "chinese": "Make it CHINESE STYLE with soy sauce, ginger, garlic, sesame oil stir-fry.",
            "mexican": "Make it MEXICAN STYLE with cumin, lime, coriander, and chili.",
            "simple":  "Keep it EXTREMELY SIMPLE — under 5 ingredients, under 10 minutes.",
            "vegan":   "Convert to a VEGAN version using only plant-based ingredients.",
        }
        variation_note = f"\nSTYLE: {variation_notes.get(variation, '')}"

    system_prompt = f"""You are FitFuel AI, an expert fitness nutritionist and chef.
GOAL: {profile['label']}
Protein: {round(profile['protein_pct']*100)}% | Carbs: {round(profile['carb_pct']*100)}% | Fat: {round(profile['fat_pct']*100)}%
Note: {profile['prompt_note']}
MEAL TIMING: {timing_note or 'General meal'}
SERVINGS: {servings}
ALLOWED INGREDIENTS:\n{ingredient_list}
PLUS: salt, black pepper, olive oil, lemon juice, garlic, ginger, any spice.
DIETARY: {dietary_note or 'No restrictions'}{single_note}{variation_note}{mem_text}"""

    user_prompt = f"""Create a FITNESS RECIPE using: {', '.join(filtered_ings)}
Goal: {profile['label']} | Timing: {meal_timing} | Servings: {servings}

Format:
🏋️ [Dish Name] — {profile['label']}
[One-line fitness benefit]

🧬 Macros Per Serving:
  • Calories: ~X kcal
  • Protein:  ~Xg
  • Carbs:    ~Xg
  • Fat:      ~Xg

🥗 Ingredients:
- [ingredient + quantity]

📝 Steps:
1. [step]
2. [step]

⏱️ Time: X minutes
🏆 Fitness Tip: [tip]"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            max_tokens=800, temperature=0.25,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"[AI] Error: {e}")
        return None

def generate_direct_fitness_recipe(dish_name, goal="fat_loss", dietary=None, variation=None):
    profile = FITNESS_PROFILES.get(goal, FITNESS_PROFILES["maintenance"])
    dietary = dietary or set()
    dietary_note = build_dietary_note(dietary)
    variation_text = f" Make it {variation} style." if variation else ""
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": (
                    f"You are FitFuel AI. Rewrite any dish to be FITNESS-OPTIMIZED for: {profile['label']}. "
                    f"Rules: {profile['prompt_note']} "
                    f"Dietary: {dietary_note or 'No restrictions'} "
                    "Always provide full macro breakdown. No deep frying."
                )},
                {"role": "user", "content": (
                    f"Give me a COMPLETE FITNESS-OPTIMIZED recipe for: {dish_name}\n"
                    f"Goal: {profile['label']}{variation_text}\n"
                    "Include: ingredients, steps, macros per serving, fitness benefit, pro tip."
                )},
            ],
            max_tokens=900, temperature=0.3,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"[DirectRecipe] Error: {e}")
        return None

def generate_fitness_meal_plan(ingredients, days=3, goal="fat_loss", weight=70, calories_target=2000):
    profile = FITNESS_PROFILES.get(goal, FITNESS_PROFILES["maintenance"])
    macros  = calculate_macros(calories_target, goal)
    prompt  = f"""You are FitFuel AI — fitness meal planning expert.
Goal: {profile['label']} | Calories: {macros['calories']} kcal | Protein: {macros['protein']}g | Carbs: {macros['carbs']}g | Fat: {macros['fat']}g
Available ingredients: {', '.join(ingredients) if ingredients else 'any common fitness ingredients'}
Pantry basics: salt, pepper, olive oil, spices, lemon, garlic.

Create a {days}-day FITNESS MEAL PLAN.
Each day: Breakfast, Pre-Workout Snack, Lunch, Post-Workout Meal, Dinner.

FORMAT:
📅 DAY 1 — Total: ~{macros['calories']} kcal
🌅 Breakfast: <dish> | ~X kcal | P:Xg C:Xg F:Xg | X mins
🏋️ Pre-Workout: <dish> | ~X kcal | ...
☀️ Lunch: <dish> | ~X kcal | ...
💪 Post-Workout: <dish> | ~X kcal | ...
🌙 Dinner: <dish> | ~X kcal | ...
(repeat for each day)
End with a 💡 weekly tip."""
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a certified sports nutritionist and meal planner."},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=1200, temperature=0.35,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"[MealPlan] Error: {e}")
        return "Could not generate meal plan. Please try again."

# ==============================
# 📊 CALORIE TRACKER
# ==============================
def log_calories(user_id, calories):
    state = get_user_state(user_id)
    state["calories_logged_today"] += calories
    logged    = state["calories_logged_today"]
    target    = state["profile"].get("calories", 2000)
    remaining = target - logged
    bar_filled = min(round((logged / max(target, 1)) * 10), 10)
    bar = "🟩" * bar_filled + "⬜" * (10 - bar_filled)
    return f"""## 📊 Today's Calorie Log

{bar} {round((logged / max(target, 1)) * 100)}%

| | Calories |
|--|--|
| ✅ Logged | {logged} kcal |
| 🎯 Target | {target if target > 0 else 'Set your profile first'} kcal |
| 📉 Remaining | {remaining if target > 0 else '—'} kcal |

💡 Tell me what you ate to log more: e.g. *"I ate 200g chicken and 100g rice"*"""

# ==============================
# ✅ VERIFY & FALLBACK
# ==============================
def verify_recipe(output, ingredients):
    if not output or len(output) < 80:
        return False
    found = sum(1 for i in ingredients if i.lower() in output.lower())
    has_steps = any(w in output.lower() for w in ["step", "cook", "add", "heat", "mix", "grill", "boil"])
    return (found > 0 or len(ingredients) == 1) and has_steps

def fallback_recipe(ingredients, goal):
    profile = FITNESS_PROFILES.get(goal, FITNESS_PROFILES["maintenance"])
    main = ingredients[0] if ingredients else "protein source"
    veg  = next((i for i in ingredients if i in ["spinach","broccoli","kale","carrot","cabbage"]), "vegetables")
    return f"""## 🏋️ Quick {main.title()} Fitness Bowl — {profile['label']}

### 🧬 Macros (estimate)
| | Per Serving |
|--|--|
| 🔥 Calories | ~350 kcal |
| 💪 Protein | ~35g |
| 🌾 Carbs | ~25g |
| 🧈 Fat | ~10g |

### 🥗 Ingredients
{chr(10).join(f'- {i}' for i in ingredients)}
- Salt, pepper, olive oil, lemon, garlic

### 📝 Steps
1. Season {main} with salt, pepper, lemon
2. Grill/pan-sear over medium heat for 6–8 min per side
3. {'Steam or sauté ' + veg + ' for 3–4 min' if veg != 'vegetables' else 'Add vegetables of choice, sauté 3–4 min'}
4. Plate together. Drizzle lemon. Serve hot.

⏱️ Time: ~15 min
🏆 Fitness Tip: {profile['prompt_note'][:100]}..."""

# ==============================
# 🔊 TEXT TO SPEECH
# ==============================
def text_to_speech(text):
    try:
        clean = re.sub(r'\*+|#+|\|[-:]+\||[|]', '', text)
        clean = ''.join(c for c in clean if ord(c) < 128)
        clean = clean[:600]

        async def generate():
            communicate = edge_tts.Communicate(clean, voice="en-IN-NeerjaNeural")
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as f:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])
                return f.name

        path = asyncio.run(generate())
        with open(path, 'rb') as f:
            audio_b64 = base64.b64encode(f.read()).decode()
        return audio_b64
    except Exception as e:
        print(f"[TTS] Error: {e}")
        return ""

# ==============================
# 📸 FRIDGE SCAN
# ==============================
def detect_ingredients_from_image(image_path):
    if not image_path:
        return None
    try:
        img = Image.open(image_path).convert("RGB")
        img.thumbnail((512, 512))
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            img.save(tmp.name, format="JPEG")
            tmp_path = tmp.name
        with open(tmp_path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode()
        os.remove(tmp_path)
        response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_data}"}},
                {"type": "text", "text": "List ONLY the food ingredients you can clearly see. Format: ingredient1, ingredient2, ... (comma-separated, max 10). Nothing else."},
            ]}],
            max_tokens=150,
        )
        detected = response.choices[0].message.content.strip()
        for prefix in ["I can see:", "Ingredients:", "I see:", "The ingredients are:"]:
            if detected.lower().startswith(prefix.lower()):
                detected = detected[len(prefix):].strip()
        return detected or None
    except Exception as e:
        print(f"[Vision] Error: {e}")
        return None

# ==============================
# 🎯 INTENT DETECTION
# ==============================
def _word_in(word, text):
    return bool(re.search(r'\b' + re.escape(word) + r'\b', text))

def detect_intent(text):
    t = text.lower()

    if any(_word_in(g, t) for g in ["hi", "hello", "hey", "namaste"]):
        return "greeting"
    if any(w in t for w in ["thank", "bye", "goodbye", "see you"]):
        return "closing"
    if re.search(r'(macro|calorie|nutrition|protein).*(of|in|for)\s+\w+', t):
        return "macro_lookup"
    if any(w in t for w in ["macros of", "calories in", "nutrition of", "how much protein in"]):
        return "macro_lookup"
    if any(w in t for w in ["substitute", "replace", "alternative", "swap", "instead of"]):
        return "substitution"
    if any(w in t for w in ["shopping list", "grocery list", "buy list", "what to buy"]):
        return "shopping_list"
    if any(w in t for w in ["supplement", "creatine", "bcaa", "pre workout", "post workout",
                             "whey", "omega", "vitamin", "magnesium", "caffeine", "casein"]) and \
       any(w in t for w in ["when", "take", "should", "timing", "guide", "how much"]):
        return "supplement"
    if any(w in t for w in ["water", "hydration", "drink", "hydrate"]) and \
       any(w in t for w in ["how much", "intake", "daily", "need", "kg"]):
        return "water_intake"
    if re.search(r'log(ged)?\s+(\d+)\s*(kcal|calories?|cal)', t) or \
       re.search(r'(ate|eaten|had)\s+\d+', t):
        return "calorie_log"
    if any(w in t for w in ["make it", "make this", "same but"]) and \
       any(w in t for w in ["spicy", "indian", "chinese", "mexican", "simple", "vegan", "hot", "desi"]):
        return "variation"
    if any(w in t for w in ["meal plan", "plan my", "weekly plan", "day plan"]):
        return "meal_plan"
    if any(w in t for w in ["recipe for", "how to make", "how to cook", "give me recipe"]):
        return "direct_recipe"

    words = t.split()
    for word in words:
        if len(word) > 2 and word in FITNESS_INGREDIENTS:
            return "recipe"
        match = process.extractOne(word, FITNESS_INGREDIENTS, score_cutoff=80)
        if match:
            return "recipe"

    return "chat"

# ==============================
# 🍳 RECIPE REPLY HELPER
# ==============================
def _generate_recipe_reply(state, memories, user_id="default"):
    """Build and return (reply_text, audio_b64) from current state."""
    goal    = state["goal"]
    profile = FITNESS_PROFILES[goal]
    dietary = state.get("dietary", set())
    variation = state.get("last_variation")

    recipe = generate_fitness_recipe(
        state["ingredients"], goal=goal,
        meal_timing=state["meal_timing"],
        servings=state["servings"],
        memories=memories, dietary=dietary, variation=variation,
    )
    if not verify_recipe(recipe, state["ingredients"]):
        recipe = fallback_recipe(state["ingredients"], goal)

    save_memory(user_id, f"Made {goal} recipe: {', '.join(state['ingredients'])}")
    nutrition    = calculate_nutrition(state["ingredients"], state["servings"])
    metrics      = get_cooking_metrics(state["ingredients"])
    timing_tip   = MEAL_TIMING.get(state["meal_timing"], "")
    timing_block = f"\n📍 Meal Timing: {timing_tip}\n" if timing_tip else ""
    diet_block   = f"\n🥗 Dietary: {', '.join(d.replace('_',' ').title() for d in dietary)}\n" if dietary else ""

    reply     = (f"### 🎯 Goal: {profile['label']}{timing_block}{diet_block}\n\n"
                 f"{recipe}\n\n{nutrition}\n\n{metrics}")
    audio_b64 = text_to_speech(recipe)
    state["last_variation"] = None
    return reply, audio_b64

# ==============================
# 🌐 FLASK ROUTES
# ==============================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/reset", methods=["POST"])
def reset_state():
    clear_user_state("default")
    return jsonify({"status": "ok", "message": "State cleared"})

@app.route("/api/chat", methods=["POST"])
def chat():
    data    = request.json
    message = data.get("message", "")
    history = data.get("history", [])
    user_id = "default"

    # Normalize input + compute corrections
    normalized  = normalize_fitness_input(message)
    fixed       = fix_spelling(normalized)
    corrections = compute_corrections(normalized, fixed)

    state    = get_user_state(user_id)
    pending  = state.get("pending")
    memories = get_memory(user_id, fixed)
    audio_b64 = ""
    reply     = ""

    # ══════════════════════════════════════════
    # PENDING STATE MACHINE
    # Handle these BEFORE calling update_state
    # so intent/ingredient extraction doesn't
    # interfere with goal/diet answers.
    # ══════════════════════════════════════════

    if pending == "awaiting_goal":
        goal = extract_goal_from_text(fixed)
        if goal:
            state["goal"]     = goal
            state["goal_set"] = True
            state["pending"]  = None
            goal_label        = FITNESS_PROFILES[goal]["label"]

            if not state.get("diet_set"):
                state["pending"] = "awaiting_diet"
                reply = (
                    f"**{goal_label}** — let's go! 💪\n\n"
                    f"One quick thing — what's your diet type? Just type:\n\n"
                    f"- **vegetarian** 🥗 *(eggs & dairy ok)*\n"
                    f"- **vegan** 🌿 *(plants only)*\n"
                    f"- **non-vegetarian** 🍗 *(eat everything)*"
                )
            elif state["ingredients"]:
                reply, audio_b64 = _generate_recipe_reply(state, memories, user_id)
            else:
                reply = (f"Got it! Working on **{goal_label}** 🎯\n\n"
                         f"Now tell me what ingredients you have and I'll build your recipe! 🥘")
        else:
            reply = (
                "I didn't quite catch that! Please type your goal:\n\n"
                "- **fat loss** 🔥\n"
                "- **muscle gain** 🏋️\n"
                "- **endurance** 🏃\n"
                "- **maintenance** ⚖️"
            )

        history.append({"role": "assistant", "content": reply})
        return jsonify({"reply": reply, "history": history, "audio": audio_b64, "corrections": corrections})

    elif pending == "awaiting_diet":
        diet = extract_diet_from_text(fixed)
        if diet is not False:
            # diet == 'non_veg' means no restriction, just mark as answered
            if diet and diet != "non_veg":
                state["dietary"].add(diet)
            state["diet_set"] = True
            state["pending"]  = None

            if state["ingredients"]:
                reply, audio_b64 = _generate_recipe_reply(state, memories, user_id)
            else:
                reply = "Got it! Now tell me what ingredients you have and I'll cook something up 🥘"
        else:
            reply = (
                "Could you clarify your diet type?\n\n"
                "- Type **vegetarian** 🥗\n"
                "- Type **vegan** 🌿\n"
                "- Type **non-vegetarian** 🍗"
            )

        history.append({"role": "assistant", "content": reply})
        return jsonify({"reply": reply, "history": history, "audio": audio_b64, "corrections": corrections})

    # ══════════════════════════════════════════
    # NORMAL FLOW
    # ══════════════════════════════════════════
    intent = detect_intent(fixed)
    state  = update_state(user_id, fixed)
    goal   = state["goal"]
    profile = FITNESS_PROFILES[goal]
    dietary = state.get("dietary", set())
    variation = state.get("last_variation")

    # ── Route by intent ──

    if intent == "closing":
        reply = "Stay consistent, stay strong! 💪 Come back anytime!"

    elif intent == "greeting":
        reply = WELCOME_MSG

    elif intent == "macro_lookup":
        for trigger in ["macros of", "calories in", "nutrition of", "macros in",
                        "how much protein in", "protein in"]:
            if trigger in fixed:
                ing = fixed.replace(trigger, "").strip().split()[0]
                reply = quick_macro_lookup(ing)
                break
        else:
            words = fixed.split()
            reply = quick_macro_lookup(words[-1]) if words else "Tell me the ingredient name!"

    elif intent == "substitution":
        reply = get_substitution(fixed)

    elif intent == "shopping_list":
        days = 7 if "week" in fixed else 3
        reply = generate_shopping_list(goal, days)

    elif intent == "supplement":
        reply = get_supplement_guide(fixed, goal)

    elif intent == "water_intake":
        if not re.search(r'\d+\s*kg', fixed) and state["profile"].get("weight"):
            fixed += f" {state['profile']['weight']}kg"
        reply = get_water_intake_response(fixed)

    elif intent == "calorie_log":
        cal_match = re.search(r'(\d+)\s*(kcal|calories?|cal)', fixed)
        if cal_match:
            calories = int(cal_match.group(1))
        else:
            calories = sum(
                NUTRITION_DB.get(w, {}).get("calories", 0)
                for w in fixed.split() if w in NUTRITION_DB
            ) or 300
        reply = log_calories(user_id, calories)

    elif intent == "variation":
        if state["ingredients"]:
            recipe = generate_fitness_recipe(
                state["ingredients"], goal=goal,
                meal_timing=state["meal_timing"],
                servings=state["servings"], memories=memories,
                dietary=dietary, variation=variation,
            )
            if not verify_recipe(recipe, state["ingredients"]):
                recipe = fallback_recipe(state["ingredients"], goal)
            reply = f"### 🎨 {variation.title() if variation else 'Variation'} Style!\n\n{recipe}"
            audio_b64 = text_to_speech(recipe)
        else:
            reply = "Tell me your ingredients first, then I'll make a variation! 🍳"

    elif intent == "meal_plan":
        days       = 5 if "week" in fixed else 3
        cal_target = state["profile"].get("calories", 2000)
        reply      = generate_fitness_meal_plan(
            state["ingredients"], days, goal, calories_target=cal_target
        )

    elif intent == "direct_recipe":
        dish = ""
        for trigger in ["recipe for", "how to make", "how to cook", "give me recipe", "make me"]:
            if trigger in fixed:
                dish = fixed.replace(trigger, "").strip()
                break
        if dish:
            result    = generate_direct_fitness_recipe(dish, goal, dietary, variation) \
                        or fallback_recipe(state["ingredients"], goal)
            reply     = result
            audio_b64 = text_to_speech(result)
        else:
            reply = "Which dish would you like a recipe for? Just name it!"

    elif intent == "recipe" or state["ingredients"]:
        if state["ingredients"]:
            # ── Check what context we still need ──
            if not state.get("goal_set"):
                state["pending"] = "awaiting_goal"
                ing_preview = ", ".join(state["ingredients"][:3])
                more = f" +{len(state['ingredients']) - 3} more" if len(state["ingredients"]) > 3 else ""
                reply = (
                    f"Nice, I can work with **{ing_preview}{more}**! 🥘\n\n"
                    f"What's your fitness goal? Just type:\n\n"
                    f"- **fat loss** 🔥\n"
                    f"- **muscle gain** 🏋️\n"
                    f"- **endurance** 🏃\n"
                    f"- **maintenance** ⚖️"
                )
            elif not state.get("diet_set"):
                state["pending"] = "awaiting_diet"
                reply = (
                    f"Great — going for **{profile['label']}** 🎯\n\n"
                    f"One quick question — what's your diet type?\n\n"
                    f"- Type **vegetarian** 🥗\n"
                    f"- Type **vegan** 🌿\n"
                    f"- Type **non-vegetarian** 🍗"
                )
            else:
                reply, audio_b64 = _generate_recipe_reply(state, memories, user_id)
        else:
            reply = (
                "Tell me what ingredients you have and I'll create a fitness recipe! 🥗\n\n"
                "*Example: 'I have chicken and rice' or just 'eggs'*"
            )

    else:
        # ── General chat fallback: use Groq for conversational reply ──
        if state["ingredients"]:
            ing_list = ", ".join(state["ingredients"])
            reply = (f"You've got **{ing_list}** ready to go 🥘\n"
                     f"Want me to turn them into a **{profile['label']}** recipe? Just say *'recipe'* or ask anything!")
        else:
            try:
                response = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": (
                            "You are FitFuel AI, a friendly and knowledgeable fitness meal planning assistant. "
                            "Keep responses short, warm, and helpful. "
                            "Guide users to share their ingredients so you can create a fitness recipe. "
                            "If they ask fitness/nutrition questions, answer briefly and accurately."
                        )},
                        *history[-6:],   # Last 3 turns for context
                        {"role": "user", "content": message},
                    ],
                    max_tokens=350, temperature=0.7,
                )
                reply = response.choices[0].message.content
            except Exception as e:
                print(f"[Chat] Error: {e}")
                reply = (
                    "I'm your fitness meal assistant! 🥗\n\n"
                    "Try: *'I have chicken'* to get a recipe, or ask about nutrition!"
                )

    history.append({"role": "assistant", "content": reply})
    return jsonify({"reply": reply, "history": history, "audio": audio_b64, "corrections": corrections})

@app.route("/api/profile", methods=["POST"])
def profile_calc():
    data    = request.json
    user_id = "default"
    result  = generate_fitness_profile_summary(
        data["weight"], data["height"], data["age"],
        data["gender"], data["activity"], data["goal"]
    )
    try:
        w, h, a = float(data["weight"]), float(data["height"]), int(data["age"])
        bmr    = calculate_bmr(w, h, a, data["gender"])
        tdee   = calculate_tdee(bmr, data["activity"])
        macros = calculate_macros(tdee, data["goal"])
        state  = get_user_state(user_id)
        state["profile"] = {"weight": w, "height": h, "age": a, "calories": macros["calories"]}
        state["goal"]     = data["goal"]
        state["goal_set"] = True
    except Exception:
        pass
    return jsonify({"result": result})

@app.route("/api/mealplan", methods=["POST"])
def mealplan():
    data        = request.json
    ingredients = [i.strip() for i in data["ingredients"].split(",") if i.strip()]
    result      = generate_fitness_meal_plan(
        ingredients, int(data["days"]), data["goal"],
        calories_target=int(data["calories"])
    )
    return jsonify({"result": result})

@app.route("/api/scan", methods=["POST"])
def scan():
    file = request.files.get("image")
    goal = request.form.get("goal", "fat_loss")
    if not file:
        return jsonify({"error": "No image uploaded"})
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        file.save(tmp.name)
        detected = detect_ingredients_from_image(tmp.name)
    if not detected:
        return jsonify({"error": "No ingredients detected. Try a clearer photo."})
    ingredients = [i.strip() for i in detected.split(",") if i.strip()]
    recipe = generate_fitness_recipe(ingredients, goal=goal, servings=2)
    if not recipe:
        recipe = fallback_recipe(ingredients, goal)
    return jsonify({"detected": detected, "recipe": recipe})

@app.route("/api/macros", methods=["GET"])
def macros_lookup():
    ingredient = request.args.get("ingredient", "")
    if not ingredient:
        return jsonify({"error": "Provide ?ingredient=name"})
    return jsonify({"result": quick_macro_lookup(ingredient)})

@app.route("/api/substitute", methods=["GET"])
def substitute():
    ingredient = request.args.get("ingredient", "")
    return jsonify({"result": get_substitution(ingredient)})

@app.route("/api/shopping", methods=["GET"])
def shopping():
    goal = request.args.get("goal", "fat_loss")
    days = int(request.args.get("days", 7))
    return jsonify({"result": generate_shopping_list(goal, days)})

@app.route("/api/supplement", methods=["GET"])
def supplement():
    name = request.args.get("name", "")
    goal = request.args.get("goal", "fat_loss")
    return jsonify({"result": get_supplement_guide(name, goal)})

@app.route("/api/water", methods=["GET"])
def water():
    weight   = request.args.get("weight", "70")
    activity = request.args.get("activity", "moderate")
    return jsonify({"result": get_water_intake_response(f"{weight}kg {activity}")})

if __name__ == "__main__":
    print("💪 Starting FitFuel AI…")