# AstraUserbot — Competitor Feature Matrix

**Gate:** COMP-1 / COMP-2  
**Purpose:** engineering gap audit, not marketing ranking.

Reference projects named by the roadmap:
- CipherElite
- CatUserbot
- Hikka
- Userge
- Paperplane
- UniBorg
- Kaguya
- Project Akasha

Public reference evidence checked during the Phase 10 audit includes Hikka's documented forms/galleries/inline UX and API protection, CatUserbot's Telethon-based group-management focus, and CipherElite's plugin/assistant-oriented startup and feature surface.

| Feature family | Reference signal | Astra status | Catch-up action |
|---|---|---|---|
| Help/discovery | Mature userbots expose command discovery | Covered | Keep deterministic help/ownership registry |
| Group moderation | CatUserbot and similar projects emphasize moderation | Covered | Existing bounded moderation surface retained |
| Productivity | Mature modules commonly include utilities/notes/helpers | Covered | Existing productivity family retained |
| Inline UX | Hikka documents forms/galleries/lists | Covered foundation | Do not add duplicate low-value UI commands in Phase 10 |
| API protection | Hikka documents API rate protection | Covered | Telegram traffic governor is the platform authority |
| Search/inspection | Mature ecosystems expose inspection/search utilities | Covered | IntelGraph + Search + media/case inspection retained |
| Media tooling | Mature ecosystems provide conversion/extraction tools | Covered | Existing media/media-intel services retained |
| AI interaction | Current userbots increasingly expose AI commands | Covered | Existing provider-independent AI surface retained |
| Security analysis | Defensive security is a recurring ecosystem concern | **Phase 10 catch-up** | Add SEC-1/2/3 |
| Plugin metadata | Mature ecosystems rely on module/plugin metadata | **Phase 10 catch-up** | SDK-1 |
| Compatibility/registry | Large module ecosystems need discovery and compatibility controls | **Phase 10 catch-up** | SDK-2 |
| Durable recovery | Not a typical competitor differentiator | Astra platform strength | Preserve JobEngine/recovery contracts |
| Evidence/provenance | Not generally a userbot feature primitive | Astra intelligence strength | Preserve IntelGraph/source/time evidence |
| Process isolation | Not assumed by plugin ecosystems | Astra platform strength | Preserve actual Bubblewrap enforcement |
| Zero-cost architecture | Competitor deployments vary | Astra constraint | No paid or mandatory hosted dependency |

## COMP-2 decision

The audit does **not** justify copying competitor command volume. The useful gaps that belong in this phase are the defensive security layer and sustainable plugin extension tooling. The remaining reference categories are already covered by the existing product/intelligence programs or are deliberately outside Astra's architecture constraints.

No new competitor-derived feature is added merely to increase command count.

## Reference evidence

- Hikka README: https://github.com/hikariatama/Hikka
- CatUserbot README: https://github.com/TgCatUB/catuserbot
- CipherElite source: https://github.com/rishabhops/CipherElite

Hikka's public documentation describes inline forms, galleries, lists, API protection, UI/UX and module compatibility. CatUserbot describes a Telethon-based userbot with group-management and utility goals. CipherElite's public source shows a plugin-oriented startup and assistant surface.

These references establish feature families only; they are not architectural authorities.
