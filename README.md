# Aaron Erlich Academic Website

This is a Quarto-based website for Aaron Erlich's academic profile, migrated from WordPress/Bluehost to GitHub Pages.

## Local Development

1. Install Quarto: https://quarto.org/docs/get-started/

2. Preview the site locally:
```bash
quarto preview
```

3. Render the site:
```bash
quarto render
```

## Publishing to GitHub Pages

1. Create a new repository on GitHub (e.g., `aaronerlich.com` or `website`)

2. Initialize git and push:
```bash
git init
git add .
git commit -m "Initial Quarto site"
git remote add origin https://github.com/YOUR-USERNAME/REPO-NAME.git
git branch -M main
git push -u origin main
```

3. Configure GitHub Pages:
   - Go to repo Settings → Pages
   - Source: Deploy from a branch
   - Branch: `main`
   - Folder: `/docs`
   - Save

4. Your site will be live at: `https://YOUR-USERNAME.github.io/REPO-NAME/`

## Custom Domain Setup (aaronerlich.com)

### In Namecheap:
1. Log into Namecheap
2. Domain List → Manage → Advanced DNS
3. Delete existing records pointing to Bluehost
4. Add these DNS records:

```
Type      Host    Value                     TTL
A         @       185.199.108.153           Automatic
A         @       185.199.109.153           Automatic
A         @       185.199.110.153           Automatic
A         @       185.199.111.153           Automatic
CNAME     www     YOUR-USERNAME.github.io   Automatic
```

### In GitHub:
1. Repo Settings → Pages
2. Custom domain: `aaronerlich.com`
3. Save
4. Wait for DNS check (up to 24 hours, usually faster)
5. Once verified, enable "Enforce HTTPS"

## Updating Content

1. Edit the `.qmd` files
2. Run `quarto render`
3. Commit and push:
```bash
git add .
git commit -m "Update content"
git push
```

## Site Structure

- `index.qmd` - Home/About page
- `lab.qmd` - DemoTIP Laboratory
- `cv.qmd` - Curriculum Vitae
- `research.qmd` - Publications
- `teaching.qmd` - Teaching info
- `r-tutorials.qmd` - R Tutorials
- `resources/` - Resource pages
  - `georgia-bib.qmd`
  - `letters.qmd`
  - `thesis-internships.qmd`
  - `writing.qmd`

## TODO

- [ ] Add full CV content to `cv.qmd` or add `files/Erlich_CV.pdf`
- [ ] Download `paper_advice.pdf` from WordPress and add to `files/`
- [ ] **Download images from WordPress** (see IMAGE-MIGRATION-GUIDE.md)
  - [ ] Slider photos for homepage
  - [ ] Lab member headshots
  - [ ] Lab activity photos
  - [ ] Your profile photo
  - [ ] Bike tour photo
- [ ] Once images added, replace `index.qmd` with `index-with-images.qmd`
- [ ] Once images added, replace `lab.qmd` with `lab-with-images.qmd`
- [ ] Add R Tutorials content
- [ ] Add Georgia Bibliography content
- [ ] Add Undergraduate Thesis/Internships instructions
- [ ] Embed office hours booking widget in teaching.qmd
- [ ] Test all links

## About Images

Your current WordPress site has images (slider, headshots, etc.) that are hosted on Bluehost. I've:

1. **Created versions without images** (current `index.qmd` and `lab.qmd`) that work immediately
2. **Created versions with image placeholders** (`index-with-images.qmd` and `lab-with-images.qmd`) 
3. **Created a guide** (`IMAGE-MIGRATION-GUIDE.md`) showing which images to download and how

**When you're ready to add images:**
1. Follow the IMAGE-MIGRATION-GUIDE.md
2. Download images from WordPress
3. Put them in the `images/` folder
4. Replace the main files with the `-with-images` versions
5. Uncomment the image references

**OR just launch without images initially** - the site works fine without them, you can add images later!
