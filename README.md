# VainAsherStudios Wiki.js AI Refinery — Community Ops Upgrade

This is the feature-rich local workbench for turning raw imported Markdown into a VainAsherStudios-owned Wiki.js knowledge base.

It is designed for your current situation: around **1,500 raw Markdown files** split across multiple source directories, mostly from hosting/reference sources, with VAS-specific rewriting for:

- website hosting
- website development
- managed IT
- business email setup
- AI workflows
- gaming community operations
- Minecraft / Project Zomboid / Rust community moderation
- moderator/admin training
- YouTube, LinkedIn, Twitch, and Discord content

## Install and run on Windows PowerShell

```powershell
cd C:\dev\wikijs_ai_refinery_vas
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn refinery.app:app --reload --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

## Main pages

```text
/             In-flight document queue with pagination and filters
/bulk         Bulk Workbench for multi-directory imports and batch updates
/connectors   One-off source connector imports
/context      VAS Context Library editor
/docs/{id}    Browser editor for metadata + Markdown + transform actions
```

## Recommended workflow for 1,500 raw Markdown files

Go to **Bulk Workbench** and paste one source directory per line:

```text
bisecthosting|C:\docs\raw\bisect
apexhosting|C:\docs\raw\apex
pebblehosting|C:\docs\raw\pebble
```

Use `0` as the limit to import all files.

The importer will recursively import `.md` files and classify them into the review queue.

## Source governance

Imported third-party/reference content is intentionally not trusted as canonical VAS content.

Examples:

```yaml
source_org: bisecthosting
source_role: employer_reference
reuse_policy: rewrite_required
canonical: false
rewrite_status: needs_rewrite
```

```yaml
source_org: apexhosting
source_role: competitor_reference
reuse_policy: rewrite_required
canonical: false
rewrite_status: needs_rewrite
```

Documentation for any service VAS manages, operates, or maintains (Authentik, Pterodactyl, Rust, Canvas, and the wider self-hosted stack) is imported as upstream reference. Label the import with the tool name and the tool becomes the service automatically:

```yaml
source_org: authentik
source_role: vendor_documentation
service: authentik
reuse_policy: rewrite_required
canonical: false
rewrite_status: needs_rewrite
```

Treat these as reference only: adapt them into VAS-owned runbooks/SOPs, never republish verbatim, and check the upstream licence. Add a new tool's docs by appending one line to `MANAGED_SERVICE_DOC_ORGS` in `refinery/core.py` (and `source_orgs` in `taxonomy.yml` if you want it in the UI dropdowns).

VAS-owned transformed drafts become:

```yaml
source_org: vainasherstudios
source_role: owned
reuse_policy: owned_original
authority: draft
rewrite_status: draft_generated
```

## Bulk triage

After importing, use the filters on `/` to narrow documents by:

- source organisation
- service
- doc type
- rewrite status
- authority
- text search

Use `/bulk` to apply bulk actions to a filtered slice, such as:

```text
source_org = apexhosting
service = minecraft
set adaptation_action = rewrite_into_moderation_playbook
add tag = community-candidate
```

or:

```text
source_org = ovh
service = business_email
set adaptation_action = rewrite_into_sop
```

## VAS Context Library

Go to `/context` to edit browser-based context packs.

Default packs include:

```text
brand_voice.md
service_catalogue.md
privacy_and_data_rules.md
technical_stack_iac.md
gaming_community_ops.md
moderator_training_standards.md
content_channels_strategy.md
platform_minecraft_project_zomboid_rust.md
```

These packs are injected into the AI rewrite prompt as **higher authority than imported source docs**.

Add your own packs, for example:

```text
minecraft_staff_handbook.md
rust_admin_policy.md
project_zomboid_rp_rules.md
client_hosting_stack.md
wordpress_delivery_standards.md
business_email_baseline.md
youtube_training_voice.md
linkedin_content_style.md
```

## Transform targets

The browser editor can transform a reference doc into a VAS-owned draft for:

```text
rewrite_into_sop
rewrite_into_runbook
rewrite_into_customer_guide
rewrite_into_support_template
rewrite_into_policy
rewrite_into_training
rewrite_into_moderation_playbook
rewrite_into_admin_guide
rewrite_into_lesson_plan
rewrite_into_youtube_script
rewrite_into_linkedin_post
rewrite_into_twitch_outline
rewrite_into_discord_staff_guide
rewrite_into_community_announcement
```

The generated draft is added as a new in-flight document. It is **not published automatically**.

## AI model

The app works without an AI model using deterministic classification and fallback drafts.

For richer rewriting, run Ollama and provide a model in the transform form:

```powershell
ollama pull llama3.1:8b
```

Then enter:

```text
llama3.1:8b
```

in the editor transform panel.

## Publishing to Wiki.js

Set:

```powershell
$env:WIKIJS_URL="http://localhost:3000/graphql"
$env:WIKIJS_TOKEN="your-token"
```

Then use the publish button from the document editor.

## Safety model

The refinery separates:

```text
Reference/imported docs  → source evidence only
VAS transformed drafts   → editable VAS-owned working docs
Reviewed canonical docs  → Wiki.js source of truth
```

Do not publish imported third-party/employer/competitor docs directly as VAS policy. Transform, edit, review, then promote.
