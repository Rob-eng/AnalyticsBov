import asyncio
from playwright.async_api import async_playwright
import os

async def get_mercado_futuro_screenshot():
    """
    Captures a screenshot of the 'Mercado Futuro' table from Scot Consultoria.
    Returns the path to the saved screenshot.
    """
    url = "https://www.scotconsultoria.com.br/cotacoes/mercado-futuro/?ref=foo"
    output_path = "/tmp/mercado_futuro.png"
    
    async with async_playwright() as p:
        # We try to use chromium, which is standard
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            device_scale_factor=2, # High DPI for better quality
        )
        page = await context.new_page()
        
        try:
            # Navigate to the page
            await page.goto(url, wait_until="networkidle")
            
            # Handle cookie consent if visible (optional but good for clean shot)
            try:
                # Based on research, cookie button is usually identifiable
                # If it takes too long, we just proceed
                await page.click("text=Aceitar", timeout=3000)
            except:
                pass

            # Focus on the 'MERCADO FUTURO DO BOI GORDO' table
            # Based on layout research: .conteudo table is the main container
            table_selector = ".conteudo table"
            
            # Wait for the table to be visible
            await page.wait_for_selector(table_selector)
            
            # Locate the specific table (the first one)
            table = page.locator(table_selector).first
            
            # Take element screenshot
            await table.screenshot(path=output_path)
            
            return output_path
            
        except Exception as e:
            print(f"Error capturing future market screenshot: {e}")
            return None
        finally:
            await browser.close()

if __name__ == "__main__":
    # Test script
    async def test():
        path = await get_mercado_futuro_screenshot()
        if path:
            print(f"Screenshot saved to: {path}")
        else:
            print("Failed to capture screenshot.")
            
    asyncio.run(test())
