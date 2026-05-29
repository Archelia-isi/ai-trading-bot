import os

math_path = '/Users/salvatoreizzo/Desktop/progetto trading/services/math_engine/main.py'
with open(math_path, 'r') as f:
    content = f.read()

# Replace global lambda definition
content = content.replace("GLOBAL_XGBOOST_LAMBDA = 20.0", "GLOBAL_CONFIG = {\n    'xgboost_lambda': 10.0,\n    'hunter_long': 0.65,\n    'hunter_short': 0.35,\n    'segugio_long': 0.60,\n    'segugio_short': 0.40\n}")

# Replace usages
content = content.replace("reg_lambda=GLOBAL_XGBOOST_LAMBDA", "reg_lambda=GLOBAL_CONFIG['xgboost_lambda']")
content = content.replace("if prob >= 0.65:", "if prob >= GLOBAL_CONFIG['hunter_long']:")
content = content.replace("elif prob <= 0.35:", "elif prob <= GLOBAL_CONFIG['hunter_short']:")
content = content.replace("if data['label'] == 'NEGATIVE' and prob < 0.3:", "if data['label'] == 'NEGATIVE' and prob <= GLOBAL_CONFIG['segugio_short']:")
content = content.replace("if news_label == 'POSITIVE' and prob > 0.6:", "if news_label == 'POSITIVE' and prob >= GLOBAL_CONFIG['segugio_long']:")

updater_code = """
async def config_updater_loop():
    global GLOBAL_CONFIG
    while True:
        try:
            if redis_client:
                keys = ['xgboost_lambda', 'hunter_long', 'hunter_short', 'segugio_long', 'segugio_short']
                for key in keys:
                    val = await redis_client.get(f"config:{key}")
                    if val is not None:
                        GLOBAL_CONFIG[key] = float(val)
        except Exception as e:
            logger.error(f"Errore lettura config da Redis: {e}")
        await asyncio.sleep(5)
"""

# Replace the loop
import re
content = re.sub(r'async def lambda_updater_loop\(\):.*?await asyncio\.sleep\(10\)', updater_code.strip(), content, flags=re.DOTALL)

content = content.replace("asyncio.create_task(lambda_updater_loop())", "asyncio.create_task(config_updater_loop())")

with open(math_path, 'w') as f:
    f.write(content)
print("Math Engine patched.")
