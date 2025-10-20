"""
Package entrypoint for the USAGI crawler. This file contains the crawler logic moved from the top-level `main.py`.
"""

import sys
import json
import hashlib
import time
from typing import List, Dict, Any
import requests
from playwright.sync_api import sync_playwright, Page
import os
from dotenv import load_dotenv
load_dotenv()
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY', '')
if not GOOGLE_API_KEY:
    print('請先設定環境變數 GOOGLE_API_KEY（置於 .env 或系統環境）')
    sys.exit(1)

LLM_MODEL = os.getenv('LLM_MODEL', 'gemini-2.0-flash-exp')
MAX_STEPS = 200
ACTION_TRY_LIMIT = 3
LLM_TEMPERATURE = 0.2


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def short(s: str, n: int = 200) -> str:
    return s if len(s) <= n else s[:n] + '...'


def observe(page: Page) -> Dict[str, Any]:
    dom = page.evaluate('''() => {
        function cloneNode(n){
            const attrsToKeep = ['id','class','name','placeholder','aria-label','role','href','type','title','alt','value'];
            const o = {tag: n.tagName.toLowerCase(), attrs: {}, text: ''};
            for(const a of Array.from(n.attributes || [])){
                if (attrsToKeep.includes(a.name)) o.attrs[a.name] = a.value;
            }
            o.text = (n.textContent || '').trim().slice(0,200);
            return o;
        }
        
        // Generate unique IDs for elements
        let idCounter = 0;
        
        // Collect clickable elements with IDs
        const clickables = Array.from(document.querySelectorAll('a,button,input[type=button],input[type=submit],[role=button]'))
            .slice(0,100).map(el => {
                const info = cloneNode(el);
                info.element_id = idCounter++;
                el.setAttribute('data-usagi-id', info.element_id);
                try{ info.accessible = el.getAttribute && (el.getAttribute('aria-label') || el.getAttribute('title') || ''); }catch(e){info.accessible=''}
                return info;
            });
        
        // Collect fillable elements (input, textarea) with IDs
        const fillables = Array.from(document.querySelectorAll('input:not([type=button]):not([type=submit]):not([type=hidden]),textarea,select'))
            .slice(0,100).map(el => {
                const info = cloneNode(el);
                info.element_id = idCounter++;
                el.setAttribute('data-usagi-id', info.element_id);
                try{ 
                    info.accessible = el.getAttribute && (el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder') || '');
                    info.current_value = el.value || '';
                }catch(e){
                    info.accessible='';
                    info.current_value='';
                }
                return info;
            });
            
        return {title: document.title || '', url: location.href, clickables, fillables};
    }''')

    try:
        a11y = page.accessibility.snapshot()
    except Exception:
        a11y = {}

    screenshot_bytes = page.screenshot(type='png', full_page=False)
    screenshot_hash = sha256_bytes(screenshot_bytes)

    dom_finger = sha256_bytes(json.dumps(dom, sort_keys=True).encode('utf-8'))

    summary = f"{dom.get('title','')} {dom.get('url','')} clickables:{len(dom.get('clickables',[]))} fillables:{len(dom.get('fillables',[]))}"

    return {
        'dom': dom,
        'a11y': a11y,
        'screenshot': screenshot_bytes,
        'screenshot_hash': screenshot_hash,
        'dom_finger': dom_finger,
        'summary': summary
    }


def make_planner_prompt(state_summary: str, clickables: List[Dict[str, Any]], fillables: List[Dict[str, Any]], clicked_ids: set = None) -> str:
    if clicked_ids is None:
        clicked_ids = set()
    
    # Format clickables with ID and clicked status
    clickable_lines = []
    for c in clickables[:12]:
        eid = c.get('element_id', '?')
        clicked = '✓' if eid in clicked_ids else ' '
        line = f"[{clicked}] ID:{eid} tag:{c.get('tag')}, text:{short(c.get('text',''))}, aria:{short(c.get('attrs',{}).get('aria-label','') or c.get('accessible',''))}, attr_id:{c.get('attrs',{}).get('id','')}"
        clickable_lines.append(line)
    clickables_text = '\n'.join(clickable_lines)
    
    # Format fillables with ID
    fillable_lines = []
    for f in fillables[:12]:
        eid = f.get('element_id', '?')
        line = f"ID:{eid} tag:{f.get('tag')}, type:{f.get('attrs',{}).get('type','text')}, name:{f.get('attrs',{}).get('name','')}, placeholder:{short(f.get('attrs',{}).get('placeholder',''))}, current_value:{short(f.get('current_value',''))}"
        fillable_lines.append(line)
    fillables_text = '\n'.join(fillable_lines) if fillable_lines else "(none)"
    
    prompt = f"""
You are a web testing planner. Current page summary:
{state_summary}

Clickable elements (✓ = already clicked in this state):
{clickables_text}

Fillable elements:
{fillables_text}

Mission: Explore the site and find new unique states. Prefer unclicked elements [ ] and filling forms.
Return a JSON array of up to 3 actions. Each action must be an object with fields:
- action_type: "click" | "fill" | "navigate" | "noop"
- target_id: element_id (required, use the ID: number shown above)
- fill_value: (optional, only for fill actions, suggest realistic test values)
- rationale: short explanation
- confidence: 0.0 to 1.0

Example:
[
  {{"action_type":"fill","target_id":5,"fill_value":"test@example.com","rationale":"Fill email field","confidence":0.9}},
  {{"action_type":"click","target_id":8,"rationale":"Submit form","confidence":0.95}}
]

Make sure output is pure JSON.
"""
    return prompt


from usagi.google_llm import GoogleGenerativeLLM


def call_llm(prompt: str) -> str:
    llm = GoogleGenerativeLLM(model_name=LLM_MODEL, api_key=GOOGLE_API_KEY, temperature=LLM_TEMPERATURE)
    try:
        return llm(prompt)
    except Exception as e:
        print('Google LLM error:', e)
        print('Planner will fallback to exploration (empty actions).')
        return ''



def plan_actions(state: Dict[str, Any], clicked_ids: set = None) -> List[Dict[str, Any]]:
    if clicked_ids is None:
        clicked_ids = set()
    prompt = make_planner_prompt(
        state['summary'], 
        state['dom']['clickables'], 
        state['dom'].get('fillables', []),
        clicked_ids
    )
    raw = call_llm(prompt)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        import re
        m = re.search(r"(\[.*\])", raw, re.S)
        if m:
            try:
                parsed = json.loads(m.group(1))
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass
    print('LLM 回傳無法解析為 JSON，原始回覆前 1000 字：')
    print(raw[:1000])
    return [{'action_type': 'noop', 'rationale': 'parse_failed', 'confidence': 0}]


def escape_for_text_selector(s: str) -> str:
    return s.replace('\\', '\\\\').replace('/', '\\/')


def find_and_act(page: Page, action: Dict[str, Any], clickables: List[Dict[str, Any]], fillables: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Execute an action using element_id for precise targeting."""
    action_type = action.get('action_type', 'noop')
    target_id = action.get('target_id')
    
    if action_type == 'noop':
        return {'ok': False, 'reason': 'noop'}
    
    if target_id is None:
        return {'ok': False, 'reason': 'no_target_id'}
    
    try:
        # Handle FILL action
        if action_type == 'fill':
            fill_value = action.get('fill_value', '')
            # Find element by data-usagi-id attribute
            try:
                element = page.locator(f'[data-usagi-id="{target_id}"]').first
                element.scroll_into_view_if_needed(timeout=3000)
                element.clear(timeout=3000)
                element.fill(fill_value, timeout=3000)
                print(f"  ✓ Filled element ID:{target_id} with '{fill_value}'")
                return {'ok': True, 'action': 'fill', 'target_id': target_id}
            except Exception as e:
                print(f"  ✗ Fill failed for ID:{target_id}: {e}")
                return {'ok': False, 'reason': f'fill_error: {e}'}
        
        # Handle CLICK action
        elif action_type == 'click':
            try:
                element = page.locator(f'[data-usagi-id="{target_id}"]').first
                element.scroll_into_view_if_needed(timeout=3000)
                element.click(timeout=3000)
                print(f"  ✓ Clicked element ID:{target_id}")
                return {'ok': True, 'action': 'click', 'target_id': target_id}
            except Exception as e:
                print(f"  ✗ Click failed for ID:{target_id}: {e}")
                return {'ok': False, 'reason': f'click_error: {e}'}
        
        # Handle NAVIGATE action (for links)
        elif action_type == 'navigate':
            try:
                element = page.locator(f'[data-usagi-id="{target_id}"]').first
                element.scroll_into_view_if_needed(timeout=3000)
                element.click(timeout=3000)
                print(f"  ✓ Navigated via element ID:{target_id}")
                return {'ok': True, 'action': 'navigate', 'target_id': target_id}
            except Exception as e:
                print(f"  ✗ Navigate failed for ID:{target_id}: {e}")
                return {'ok': False, 'reason': f'navigate_error: {e}'}
        
        else:
            return {'ok': False, 'reason': f'unknown_action_type: {action_type}'}
            
    except Exception as e:
        print(f"  ✗ Action failed: {e}")
        return {'ok': False, 'reason': f'exception: {e}'}


def run(target_url: str):
    import random
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(target_url, wait_until='domcontentloaded')

        visited = set()  # Only use dom_finger for state tracking (優先級3)
        transitions = []
        state_memory = {}  # Track clicked elements per state: {dom_finger: set(element_ids)}

        for step in range(MAX_STEPS):
            print(f"\n===== STEP {step+1} =====")
            state = observe(page)
            
            # Use only dom_finger for state_id (優先級3 - 避免循環)
            state_id = state['dom_finger']
            
            # Initialize clicked_ids for this state if not exists
            if state_id not in state_memory:
                state_memory[state_id] = set()
            clicked_ids = state_memory[state_id]
            
            is_new = state_id not in visited
            if is_new:
                visited.add(state_id)
                print(f"✨ New state: {state['summary']} (states={len(visited)})")
            else:
                print(f"♻️  Seen state: {state['summary']} (clicked {len(clicked_ids)} elements here)")

            # Plan actions with memory of clicked elements (優先級3 - 狀態內記憶)
            actions = plan_actions(state, clicked_ids)
            acted = False
            
            for a in actions[:3]:
                print(f"🤖 LLM suggested: {a}")
                for t in range(ACTION_TRY_LIMIT):
                    res = find_and_act(page, a, state['dom']['clickables'], state['dom'].get('fillables', []))
                    if res.get('ok'):
                        acted = True
                        # Record the element as clicked in this state
                        if res.get('target_id') is not None:
                            clicked_ids.add(res['target_id'])
                        
                        time.sleep(0.8)
                        new_state = observe(page)
                        new_id = new_state['dom_finger']
                        transitions.append({'from': state_id, 'to': new_id, 'action': a})
                        print(f'✓ Action executed, transition to state {new_id[:16]}...')
                        break
                    else:
                        print(f'  ⚠ Action try {t+1} failed: {res.get("reason")}')
                if acted:
                    break

            # Improved fallback: randomly click an unclicked element (優先級3)
            if not acted:
                print('🔄 No action executed by LLM; fallback to random unclicked element')
                
                # Collect all clickable element IDs
                all_clickable_ids = [c.get('element_id') for c in state['dom']['clickables'] if c.get('element_id') is not None]
                
                # Filter out already clicked ones
                unclicked = [eid for eid in all_clickable_ids if eid not in clicked_ids]
                
                if unclicked:
                    # Randomly pick one
                    chosen_id = random.choice(unclicked)
                    print(f'  🎲 Randomly trying unclicked element ID:{chosen_id}')
                    
                    fallback_action = {'action_type': 'click', 'target_id': chosen_id}
                    res = find_and_act(page, fallback_action, state['dom']['clickables'], state['dom'].get('fillables', []))
                    
                    if res.get('ok'):
                        clicked_ids.add(chosen_id)
                        time.sleep(0.6)
                        print(f'  ✓ Fallback click succeeded')
                    else:
                        print(f'  ✗ Fallback click failed: {res.get("reason")}')
                else:
                    print('  ⚠ No unclicked elements available. Stopping.')
                    break

            if len(visited) > 200:
                print('🛑 Visited limit reached, stopping.')
                break

        print(f'\n🏁 Crawl finished.')
        print(f'   Unique states discovered: {len(visited)}')
        print(f'   Total transitions: {len(transitions)}')
        print(f'   Total elements interacted: {sum(len(ids) for ids in state_memory.values())}')
        browser.close()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python llm_gui_crawler.py <target_url>')
        sys.exit(1)
    target = sys.argv[1]
    run(target)
