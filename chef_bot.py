import sys
import os
import json
from curl_cffi import requests
from bs4 import BeautifulSoup
from datetime import datetime

# --- CONFIGURATION ---
RECIPE_FOLDER = "_recipes"
IMAGE_FOLDER = "assets/img"
# ---------------------

def save_image(image_url, filename):
    if not image_url: return None
    try:
        # Impersonate Chrome to download the image
        response = requests.get(image_url, impersonate="chrome110")
        if response.status_code == 200:
            filepath = os.path.join(IMAGE_FOLDER, filename)
            with open(filepath, 'wb') as f:
                f.write(response.content)
            return f"/{IMAGE_FOLDER}/{filename}"
    except Exception as e:
        print(f"⚠️  Could not download image: {e}")
    return None

def scrape_food_site(url):
    print(f"🕵️  Attempting stealth scrape: {url}")
    try:
        response = requests.get(url, impersonate="chrome110", timeout=15)
        
        if response.status_code != 200:
            print(f"❌ Server blocked us with code: {response.status_code}")
            return None

        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 1. Hunt for JSON-LD
        scripts = soup.find_all('script', type='application/ld+json')
        data = None
        
        for script in scripts:
            try:
                json_data = json.loads(script.string)
                if isinstance(json_data, list):
                    for item in json_data:
                        if 'Recipe' in item.get('@type', ''):
                            data = item
                            break
                elif 'Recipe' in json_data.get('@type', ''):
                    data = json_data
                if data: break
            except:
                continue

        if not data:
            # Fallback: Try to grab title manually
            title = soup.find('h1').get_text().strip() if soup.find('h1') else "Unknown Recipe"
            print(f"⚠️  JSON-LD not found. Creating skeleton for '{title}'...")
            return {
                "title": title,
                "ingredients": ["  (Please fill in manually)"],
                "instructions": "(Please fill in manually)",
                "image_url": None
            }

        # 2. Extract Data
        title = data.get('name', 'Unknown Recipe')
        
        # Ingredients
        ing_data = data.get('recipeIngredient', [])
        ingredients = []
        for i in ing_data:
            ingredients.append(f"  {i}")
            
        # Instructions
        instr_data = data.get('recipeInstructions', [])
        instructions = ""
        if isinstance(instr_data, list):
            for step in instr_data:
                if isinstance(step, dict):
                    instructions += f"{step.get('text', '')}\n\n"
                else:
                    instructions += f"{step}\n\n"
        else:
            instructions = instr_data

        # Image
        img_data = data.get('image', [])
        image_url = ""
        if isinstance(img_data, list):
            image_url = img_data[0]
        elif isinstance(img_data, dict):
            image_url = img_data.get('url', '')
        else:
            image_url = img_data

        return {
            "title": title,
            "ingredients": ingredients,
            "instructions": instructions,
            "image_url": image_url
        }

    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def make_recipe(url):
    data = scrape_food_site(url)

    if not data:
        print("❌ Failed to get recipe data.")
        return

    title = data['title']
    slug = title.lower().replace(" ", "-").replace("'", "").replace("’", "").replace('"', "")
    date_now = datetime.now().isoformat()
    
    image_path = ""
    if data['image_url']:
        image_filename = f"{slug}.jpg"
        image_path = save_image(data['image_url'], image_filename) or ""

    formatted_ingredients = "\n".join(data['ingredients'])

    # FOOD-SPECIFIC FRONTMATTER
    content = f"""---
title: "{title}"
date: {date_now}
category: Main
ingredients: |-
{formatted_ingredients}
source-url: {url}
image: "{image_path}"
layout: recipe
---
{data['instructions']}
"""

    filename = f"{RECIPE_FOLDER}/{datetime.now().strftime('%Y-%m-%d')}-{slug}.md"
    with open(filename, "w") as f:
        f.write(content)

    print(f"✅ Success! Created: {filename}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        make_recipe(sys.argv[1])
    else:
        url = input("Enter recipe URL: ")
        make_recipe(url)