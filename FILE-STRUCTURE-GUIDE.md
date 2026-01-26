# File Structure and Best Practices

## Directory Structure

```
aaronerlich-quarto/
├── _quarto.yml              # Site configuration
├── index.qmd                # Home page
├── lab.qmd                  # Lab page
├── cv.qmd                   # CV page (links to PDF)
├── cv-embedded-example.qmd  # Alternative: embedded CV
├── research.qmd             # Publications
├── teaching.qmd             # Teaching
├── r-tutorials.qmd          # R tutorials
├── styles.css               # Custom styling
├── CNAME                    # For custom domain
├── files/                   # PUT YOUR PDFs HERE
│   ├── Erlich_CV.pdf       # Your CV (you need to add this)
│   ├── paper_advice.pdf    # Your writing advice (download from WordPress)
│   └── README.md
├── images/                  # PUT YOUR IMAGES HERE (optional)
│   ├── profile.jpg
│   ├── slider01.jpg
│   └── ...
└── resources/               # Resource subpages
    ├── georgia-bib.qmd
    ├── letters.qmd
    ├── thesis-internships.qmd
    └── writing.qmd
```

## Relative Link Best Practices

### For Files in Same Directory
```markdown
[Link text](other-page.qmd)
[Research](research.qmd)
```

### For Files in Subdirectories
```markdown
[Link text](resources/writing.qmd)
```

### For Files in Parent Directory (from subdirectory)
```markdown
[Link text](../cv.qmd)
[PDF](../files/paper.pdf)
```

### For PDFs and Downloads
```markdown
[Download CV](files/Erlich_CV.pdf)
```

### For Images
```markdown
![Alt text](images/photo.jpg)
```

## CV: Two Options

### Option 1: Link to PDF (Recommended ✅)
- Easier to maintain
- Update once, use everywhere
- Professional standard
- Current implementation in `cv.qmd`

**To use:**
1. Put `Erlich_CV.pdf` in the `files/` directory
2. Keep `cv.qmd` as is

### Option 2: Embed Content
- All content visible on website
- Better for SEO
- More work to maintain
- See `cv-embedded-example.qmd` for template

**To use:**
1. Rename `cv-embedded-example.qmd` to `cv.qmd`
2. Fill in all your CV sections

## Adding Your Files

### Download from WordPress

1. **Your CV**: Upload to `files/Erlich_CV.pdf`

2. **Writing advice PDF**:
   - Visit: http://aaronerlich.com/wp-content/uploads/2011/02/paper_advice.pdf
   - Download it
   - Save as `files/paper_advice.pdf`

3. **Images** (optional but nice):
   - Slider images: `/wp-content/uploads/2016/12/slider*.jpg`
   - Lab member photos: `/wp-content/uploads/2024/10/*.jpg` or `.png`
   - Your bike photo: `/wp-content/uploads/2010/12/biketour.jpg`
   - Save all to `images/` directory

## Testing Locally

```bash
cd aaronerlich-quarto
quarto preview
```

Check that all links work, especially:
- Navigation menu
- CV PDF link
- Writing advice PDF link
- Internal page links

## Important: Git Commit Files

After adding PDFs/images:
```bash
git add files/
git add images/
git commit -m "Add CV and supporting files"
git push
```

Without this step, files won't appear on your live site!
