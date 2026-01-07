# AI Testing Agent - Limitations

## Overview
This document outlines the current limitations and constraints of the AI testing agent.

---

## API & Quota Limitations

### Google Gemini Free Tier Limits
| Limit Type | Value |
|------------|-------|
| Requests per minute | 15-20 |
| Requests per day | ~1500 |
| Tokens per minute | Limited |

**Impact:**
- Long exploration sessions may hit rate limits
- Each AI step consumes 1 API call
- Rate limits are **per-model** (switching models can help)
- Rate limits are **per-project** (not per-API-key)

**Workarounds:**
- Use `--max-steps` to limit API calls
- Switch between models (`gemini-2.5-flash`, `gemini-2.0-flash`)
- Wait for quota reset (daily/per-minute)
- Enable billing for higher limits

---

## Platform Limitations

### Android Only
- Currently only supports Android devices/emulators
- iOS support not implemented
- Requires Android SDK and ADB

### Appium Dependency
- Requires Appium server running
- Depends on UiAutomator2 driver
- Session timeouts can occur during long waits

---

## AI Understanding Limitations

### Element Recognition
- AI can only interact with elements visible in the UI hierarchy
- Elements not exposed to accessibility tools cannot be detected
- Custom/native views may not have proper accessibility IDs

### Context Window
- Limited to ~30 recent accessibility IDs per prompt
- Very long page sources are truncated
- May miss elements in deeply nested views

### Decision Making
- AI may make suboptimal choices
- Can get stuck in loops on similar screens
- May not understand app-specific terminology
- Complex multi-screen flows may confuse the AI

---

## Action Limitations

### Not Supported
| Action | Status |
|--------|--------|
| Multi-touch gestures | ❌ Not supported |
| Pinch to zoom | ❌ Not supported |
| Long press | ⚠️ Limited support |
| Drag and drop | ❌ Not supported |
| Hardware buttons (volume, etc.) | ❌ Not supported |
| Camera/media interactions | ❌ Not supported |
| Notifications | ❌ Not supported |
| System dialogs | ⚠️ Limited support |
| WebView content | ⚠️ Limited support |

### Timing Issues
- Fixed wait times may not match app behavior
- Animations can cause element detection failures
- Slow networks may cause timeouts

---

## Visual Detection Limitations

### VLM Constraints
- Requires screenshot upload (adds latency)
- Cannot detect subtle color differences
- May miss small text or icons
- Limited understanding of app-specific UI patterns

### False Positives/Negatives
- May report non-bugs as bugs
- May miss actual bugs
- Subjective UI issues are inconsistently detected

---

## Workflow Limitations

### Static Workflows
- Cannot adapt to unexpected states
- Fail if element IDs change
- No conditional branching within workflow
- Must be manually updated when app changes

### Variable Substitution
- Only supports `${variable}` syntax
- No computed values or expressions
- Variables must be predefined in `data` section

---

## Session & State Limitations

### No Persistence
- Each run starts fresh
- No learning from previous sessions
- Navigation memory resets between runs

### State Detection
- Cannot detect app internal state
- Limited to visible UI elements
- Cannot verify backend data

---

## Network & Performance

### Latency
- Each AI step requires API call (~1-3 seconds)
- Screenshot capture adds ~0.5 seconds
- Total step time: 2-5 seconds per action

### Reliability
- Network failures can abort sessions
- API timeouts are not always recoverable
- Emulator crashes end the session

---

## Security Limitations

### Credentials
- API keys stored in plain text `.env` file
- No encryption for sensitive data
- Test credentials visible in reports

### Privacy
- Screenshots may contain sensitive data
- Reports include full action history
- No automatic PII redaction

---

## Test Coverage Limitations

### Cannot Test
- Performance/load testing
- Security vulnerabilities
- Accessibility compliance (WCAG)
- Localization correctness
- Offline functionality
- Background processes
- Push notifications
- Deep links
- App permissions dialogs

### Limited Testing
- Complex forms (partial)
- Multi-app interactions
- Time-based features
- Location-based features

---

## Known Issues

### Current Bugs/Limitations
1. **Keyboard detection** - May not always detect keyboard state correctly
2. **Menu item timing** - Menu items sometimes not found immediately after opening
3. **Session termination** - Appium sessions can die unexpectedly during long waits
4. **Element not found** - Race conditions when elements are still loading

### Workarounds
- Add explicit `wait` actions before interactions
- Use `reset` action to recover from stuck states
- Reduce `--max-steps` to avoid long sessions
- Check emulator health if sessions fail repeatedly

---

## Recommendations

### For Best Results
1. Keep test scenarios focused and specific
2. Use `--max-steps 10-20` for targeted tasks
3. Run static workflows for regression testing
4. Use AI exploration for bug discovery
5. Monitor API quota usage
6. Ensure stable network connection
7. Keep emulator resources adequate (RAM, CPU)

### When AI Doesn't Work
1. Fall back to static workflows
2. Break complex tasks into smaller steps
3. Add more explicit instructions in task description
4. Check element accessibility IDs manually
5. Verify app is in expected initial state
