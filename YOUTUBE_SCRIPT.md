# Video Generation Assets for django-migraid

This document contains a professional transcript and a video generation prompt for creating a YouTube tutorial about `django-migraid`.

---

## 1. Video Generation Prompt (AI Tools)

**Target Tool:** Sora, HeyGen, Runway, or similar AI video generators.
**Aspect Ratio:** 16:9 (YouTube)
**Style:** Professional tech tutorial, clean UI, smooth transitions, high-contrast dark mode coding environment.

**Prompt:**
> "Create a 2-minute high-quality technical tutorial video for a developer tool called 'django-migraid'. The video should feature a split-screen layout: the left side shows a clean, modern VS Code interface in dark mode with Python migration files, and the right side shows a professional narrator (or a high-quality AI avatar) in a minimalist studio setting. 
>
> Start with a cinematic zoom-in on a Git conflict in a terminal. Show a visual representation of a 'Migration DAG' with two competing leaf nodes (0005a and 0005b) turning into a single linear line. 
> 
> Throughout the video, overlay smooth motion graphics showing CLI commands: 'python manage.py migraid doctor', 'rebase', and 'fix-conflicts'. When commands are 'executed', show the terminal output scrolling with bright green success messages. 
>
> The aesthetic should be 'SaaS professional' with deep purples and blues (matching the django-migraid branding). Include subtle background ambient tech music. The transitions should be fast-paced and rhythmic, matching the voiceover beats."

---

## 2. Video Transcript

### **Scene 1: The Hook (0:00 - 0:15)**
**Visual:** Close up of a developer's face looking frustrated at a screen. Cut to a terminal showing a `CommandError: Conflicting migrations detected`.
**Voiceover:** "We’ve all been there. You finish a feature, you rebase onto main, and suddenly... your Django migrations are a mess. Multiple leaf nodes, circular dependencies, or that dreaded 'InconsistentMigrationHistory' error. Manual fixing is risky and slow. But there’s a better way."

### **Scene 2: Introduction (0:15 - 0:30)**
**Visual:** The `django-migraid` logo appears with the text: 'Detect, Diagnose, and Auto-Fix'.
**Voiceover:** "Meet **django-migraid**. The ultimate toolkit for managing Django migrations in complex Git workflows. It doesn’t just report problems—it fixes them safely."

### **Scene 3: The Doctor Command (0:30 - 0:50)**
**Visual:** Screen recording of typing `python manage.py migraid doctor`. A list of errors (E001, E005) and warnings (W001) appears in a beautiful, color-coded table.
**Voiceover:** "Start with the `doctor` command. It scans your entire project to diagnose every known migration issue class—from gaps in numbering to circular dependencies—giving you a clear roadmap of what needs fixing."

### **Scene 4: Rebase & Fix-Conflicts (0:50 - 1:20)**
**Visual:** Animation of two diverging migration paths. One command: `migraid fix-conflicts`. The paths merge into one. 
**Voiceover:** "Working in parallel? `fix-conflicts` automatically linearizes diverging paths. Need to catch up with the main branch? The `rebase` command renumbers your local migrations to follow the latest from your base branch flawlessly. And the best part? Use the `--update-db` flag to keep your `django_migrations` table perfectly in sync, even for migrations you’ve already applied."

### **Scene 5: Safety First (1:20 - 1:45)**
**Visual:** A 'Safety Shield' icon. Show a git diff of a file being changed. Show the `--dry-run` flag in the terminal.
**Voiceover:** "Safety is built-in. Every command supports `--dry-run` so you can preview changes before they happen. `migraid` even creates a git backup ref before every write and has an automatic undo log to roll back if anything fails. It’s migration management with zero anxiety."

### **Scene 6: Conclusion (1:45 - 2:00)**
**Visual:** Commands flying by: `prune`, `sync-branch`, `graph`. End with a call to action.
**Voiceover:** "Stop fighting your migrations and start building. Install `django-migraid` today with `pip install django-migraid`. Clean migrations, happy developers."

---

## 3. Key Visual Elements to Include:
*   **Command Table:** Show the "Problems This Solves" table from the README as a quick-cut graphic.
*   **Mermaid Graph:** Show a visual of `python manage.py migraid graph` to show the DAG visualization.
*   **The --update-db Flag:** Highlight this as the "pro" feature for CI/CD and production environments.
