"""
Headless browser test for the Pocket Deck emulator.
Run: python3 emulator/test_emulator.py
The local server must be running on port 8090.
"""
import asyncio
import sys
from playwright.async_api import async_playwright

URL = "http://localhost:8090/emulator/"
TIMEOUT = 90_000  # 90s for Pyodide to load

async def run():
  async with async_playwright() as p:
    browser = await p.firefox.launch(headless=True)
    ctx = await browser.new_context()
    page = await ctx.new_page()

    errors = []
    console_msgs = []

    page.on('console', lambda m: console_msgs.append(f'[{m.type}] {m.text}'))
    page.on('pageerror', lambda e: errors.append(str(e)))

    print(f"Opening {URL} ...")
    await page.goto(URL, wait_until='domcontentloaded')

    # ── Wait for Pyodide to load ───────────────────────────────────────────
    print("Waiting for worker 'ready' (Pyodide + micropip)...")
    try:
      await page.wait_for_function(
        "() => document.getElementById('status-text')?.textContent.includes('Ready')",
        timeout=TIMEOUT
      )
      print("✓ Worker ready")
    except Exception as e:
      print(f"✗ Worker never became ready: {e}")
      for m in console_msgs[-20:]:
        print(" ", m)
      await browser.close()
      return 1

    isolated = await page.evaluate("() => self.crossOriginIsolated")
    print(f"{'✓' if isolated else '✗'} crossOriginIsolated = {isolated}")

    # ── Check app list populated ───────────────────────────────────────────
    app_items = await page.query_selector_all('.ios-list-item')
    app_count = len(app_items) - 1  # last row is the file picker
    print(f"{'✓' if app_count > 0 else '✗'} App list: {app_count} apps")

    # Position-sensitive signature: detects motion even when the white-pixel
    # count is unchanged (e.g. a shape moving across the screen).
    canvas_sum = """() => {
      const d = document.getElementById('screenCanvas').getContext('2d')
                  .getImageData(0, 0, 400, 240).data;
      let s = 0;
      for (let i = 0; i < d.length; i += 4) if (d[i]) s = (s + (i * 2654435761)) >>> 0;
      return s;
    }"""

    results = {}

    # ── hello_world (terminal) ─────────────────────────────────────────────
    print("\n── hello_world ─────────────────────────────────────────────────")
    await page.click('.ios-list-item:first-child')
    await page.click('#run-btn')
    await asyncio.sleep(3)
    term_text = await page.evaluate("() => window.getTerminalText()")
    hw_ok = 'Hello Pocket Deck' in term_text
    results['hello_world'] = hw_ok
    print(f"{'✓' if hw_ok else '✗'} terminal contains greeting")
    print("   term:", repr(term_text.strip()[:80]))
    await page.evaluate("() => requestStop()")
    await asyncio.sleep(1)

    # ── animation (graphics) ───────────────────────────────────────────────
    print("\n── animation ────────────────────────────────────────────────────")
    items = await page.query_selector_all('.ios-list-item')
    await items[1].click()
    await page.click('#run-btn')
    await asyncio.sleep(1.5)
    s1 = await page.evaluate(canvas_sum)
    await asyncio.sleep(1.2)
    s2 = await page.evaluate(canvas_sum)
    anim_ok = abs(s2 - s1) > 50 and s1 > 0
    results['animation'] = anim_ok
    print(f"{'✓' if anim_ok else '✗'} canvas animating: pixsum {s1} → {s2}")
    await page.evaluate("() => requestStop()")
    await asyncio.sleep(1)

    # ── 3D cube (graphics + dsplib) ────────────────────────────────────────
    print("\n── 3D cube ──────────────────────────────────────────────────────")
    items = await page.query_selector_all('.ios-list-item')
    await items[2].click()
    await page.click('#run-btn')
    await asyncio.sleep(1.5)
    samples = []
    for _ in range(5):
      samples.append(await page.evaluate(canvas_sum))
      await asyncio.sleep(0.4)
    nonzero = [s for s in samples if s > 0]
    changed = len(set(samples)) > 1
    cube_ok = changed and len(nonzero) >= 3
    results['cube_3d'] = cube_ok
    print(f"{'✓' if cube_ok else '✗'} cube samples: {samples}")
    await page.evaluate("() => requestStop()")
    await asyncio.sleep(1)

    # ── graphics showcase ──────────────────────────────────────────────────
    print("\n── graphics ─────────────────────────────────────────────────────")
    items = await page.query_selector_all('.ios-list-item')
    await items[3].click()
    await page.click('#run-btn')
    await asyncio.sleep(1.5)
    g1 = await page.evaluate(canvas_sum)
    await asyncio.sleep(1.0)
    g2 = await page.evaluate(canvas_sum)
    gfx_ok = abs(g2 - g1) > 50 and g1 > 0
    results['graphics'] = gfx_ok
    print(f"{'✓' if gfx_ok else '✗'} graphics animating: pixsum {g1} → {g2}")

    # verify true 1-bit output + dithering (only 0/255 values, with a mix of both)
    histo = await page.evaluate("""() => {
      const d = document.getElementById('screenCanvas').getContext('2d').getImageData(0,0,400,240).data;
      let black=0, white=0, other=0;
      for (let i=0;i<d.length;i+=4){ const v=d[i]; if(v===0)black++; else if(v===255)white++; else other++; }
      return {black, white, other};
    }""")
    frac = histo['white'] / (histo['black'] + histo['white'] + histo['other'])
    mono_ok = histo['other'] == 0 and 0.02 < frac < 0.98
    results['mono_dither'] = mono_ok
    print(f"{'✓' if mono_ok else '✗'} 1-bit mono: black={histo['black']} white={histo['white']} "
          f"gray={histo['other']} (white {frac*100:.0f}%)")

    # ── keyboard quit ('q') ────────────────────────────────────────────────
    print("\n── keyboard quit ────────────────────────────────────────────────")
    await page.focus('body')
    await page.keyboard.press('q')
    await asyncio.sleep(1.0)
    st = await page.inner_text('#status-text')
    quit_ok = st.strip().lower() in ('done', 'idle')
    results['keyboard_quit'] = quit_ok
    print(f"{'✓' if quit_ok else '✗'} app quit on 'q' → status={st!r}")

    animating = all(results.values())

    # ── Summary ───────────────────────────────────────────────────────────
    print("\n── Console output (last 15 lines) ───────────────────────────────")
    for m in console_msgs[-15:]:
      print(" ", m)
    if errors:
      print("\n── Page errors ──────────────────────────────────────────────────")
      for e in errors:
        print(" ", e)

    print("\n── Results ──────────────────────────────────────────────────────")
    for k, v in results.items():
      print(f"  {'PASS' if v else 'FAIL'}  {k}")

    await browser.close()
    return 0 if (app_count > 0 and animating) else 1

if __name__ == '__main__':
  sys.exit(asyncio.run(run()))
