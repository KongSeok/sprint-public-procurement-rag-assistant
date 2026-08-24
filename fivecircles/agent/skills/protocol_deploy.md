# Skill: Protocol for Deployment (Vercel)

## Purpose
Standardize the frontend deployment workflow, specifically targeting Vercel (Preview & Production).

## Usage
Execute this protocol when the user asks to "Deploy" (배포해) or when a feature is ready for preview.

## Protocol Steps

1.  **Pre-Deployment Check**
    - Ensure `todolist.md` tasks are completed.
    - Run `npm run type-check` (if available) or verify code integrity.

2.  **Trigger Deployment**
    - **Method A (Git Push - Preferred)**:
        - Ensure the current branch is pushed to origin.
        - Vercel will automatically detect the push and build a Preview URL.
    - **Method B (CLI - Optional)**:
        - If `vercel` CLI is configured: `npx vercel --git-branch <branch_name>`

3.  **Verification**
    - Check the PR comment for the Vercel Preview URL.
    - Run a quick smoke test on the preview environment.

4.  **Log**
    - Record the deployment status in `update.md`.
