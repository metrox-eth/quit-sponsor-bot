# Terms of service (beta draft)

Plain-language draft for the private beta. The beta is operated by an individual, not a company: it stays small, invitation-only, free, and strictly inside the tobacco scope precisely because of that. An operating entity and jurisdiction will be chosen when there is revenue to justify one, and these terms get legal review before any public, paid launch. Nothing here weakens ETHICS.md, which binds the operators.

## What this is

An AI quit-smoking sponsor: peer-style support informed by published research, running an open-source protocol (github.com/metrox-eth/quit-sponsor). It remembers your quit, keeps your logbook, and is available at the hours human support is not.

## What this is not

- **Not a medical device, not medical advice, not therapy.** Prescription options, dosing, pregnancy, cardiac or psychiatric conditions are clinician territory; the sponsor will tell you the same.
- **Not an emergency service.** If you are in physical danger or acute psychological distress, contact your local emergency number or a human crisis line (findahelpline.com). The sponsor routes you there too, but it can be slow or down; never wait on it in an emergency.
- **Not a guarantee.** Most quit attempts fail; evidence-based support improves the odds and we publish the evidence. No outcome is promised.

## Who can use it

Adults (18+). The beta is invitation-only and free.

## Your data

- **What we store:** your messages, the sponsor's replies, and your logbook (timestamps, declared events, the contract, your risk map), on an operator-controlled server.
- **What happens at inference (beta):** to generate replies, your messages are routed through Virtuals Protocol compute to the model named in the bot's `/about` command. Honest status as of July 2026: Virtuals publishes no data-retention or privacy policy for that routing layer, so for this beta you should assume message content is visible to the routing infrastructure and to the model provider. We say this plainly instead of guessing in your favor. The public launch is gated on a verified-privacy inference route (for example Venice's API, whose published architecture stores no prompts server-side and offers modes up to E2EE, or inference on hardware we control); this beta clause will be rewritten when that switch happens, and you will be notified in the bot.
- **Your rights:** export everything with one command, delete everything with one command, both executed without argument. Deletion is real.
- **What we never do:** sell your data, run ads, train models on your content, quote your logbook anywhere, or surface your quit to anyone else.
- **Aggregate learning:** anonymized lessons (what worked in a crisis, stripped of identifying details) may improve the open protocol only if you explicitly opt in.
- **Breach honesty:** if your data is ever exposed, we tell you what, when, and how, promptly and completely.

## Availability and changes

This is a beta run with best effort on personal infrastructure. It can break, pause, or change. Material changes to these terms or to data handling are announced in the bot before they apply.

## Liability

The service is provided as-is. To the maximum extent permitted by law, the operators are not liable for outcomes of your quit, missed messages, downtime, or model errors. The sponsor's medical rule applies to us too: when in doubt, the medical call is the cheap option, and it is yours to make.

## Contact

Operator contact and entity details: to be completed before public launch.
