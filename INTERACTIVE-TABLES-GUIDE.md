# Interactive Sortable Tables in Quarto

Your WordPress site has a dynamically sortable alumni table. Quarto supports this! I've created multiple versions for you.

## ⭐ Best Option: Combined (Interactive Table + Images)

**File:** `lab-full-featured.qmd`

This version has BOTH:
✅ Interactive sortable alumni table (R DT)
✅ Image placeholders for all lab members
✅ All features from both options

**How to use:**
1. Rename `lab-full-featured.qmd` to `lab.qmd`
2. Install R package: `install.packages("DT")`
3. Add your images to `images/` folder
4. Uncomment the image references
5. Run `quarto render`

This is probably what you want!

## Other Options

### Option 1: R DT Package Only (No Images)

**File:** `lab-interactive-table.qmd`

**Pros:**
- Clean, professional look
- Easy to maintain (data in R code)
- Powerful filtering and search
- Exports to CSV/Excel built-in
- You're already comfortable with R!

**Cons:**
- Requires R to be installed
- Slightly slower build time

**How to use:**
1. Rename `lab-interactive-table.qmd` to `lab.qmd` (replacing the current one)
2. Make sure you have R installed
3. Install the DT package:
```r
install.packages("DT")
```
4. Run `quarto render`

**To update the table:**
Just edit the R data frame in the code chunk - very straightforward for someone who knows R!

### Option 2: JavaScript DataTables (No R Required, No Images)

**File:** `lab-javascript-table.qmd`

**Pros:**
- No R dependency
- Works on any system
- Fast rendering
- Same features (sorting, search, pagination)

**Cons:**
- Table data is in HTML (more verbose to edit)
- Requires CDN connection (internet) to work

**How to use:**
1. Rename `lab-javascript-table.qmd` to `lab.qmd` (replacing the current one)
2. Run `quarto render`

**To update the table:**
Edit the HTML `<tr>` rows directly - more tedious than R but still straightforward.

### Option 3: Images Only (No Interactive Table)

**File:** `lab-with-images.qmd`

Static markdown table with image placeholders.

## Features Interactive Options Provide

✅ **Click column headers to sort** (ascending/descending)
✅ **Search box** to filter results
✅ **Pagination** (20 entries per page by default)
✅ **Default sort** by Graduation Year (most recent first)
✅ **All your links preserved** (theses, publications, employment)

## My Recommendation

Use **`lab-full-featured.qmd`** - it has everything:
- Interactive sortable table (easy to update via R)
- Image placeholders ready to go
- All the features of your WordPress site

Since you're comfortable with R and already use it for your work, the R DT approach is perfect.

The data is stored like this:
```r
alumni <- data.frame(
  Researcher = c("Mathieu Lavigne", "Pratik Mahajan", ...),
  Degree = c("Ph.D.", "M.A.", ...),
  Year = c(2024, 2024, ...),
  ...
)
```

Much easier to update than editing HTML tables!

## Preview Before Deciding

Try the full-featured version:
```bash
mv lab.qmd lab-original.qmd
mv lab-full-featured.qmd lab.qmd
quarto preview
```

## Example Features You Get

When rendered, users can:
- Click "Graduation Year" to sort newest→oldest or oldest→newest
- Click "Researcher" to sort alphabetically
- Type "Ph.D." in search box to see only PhD students
- Type "2020" to see all 2020 graduates
- Click "Degree" to group by degree type

Just like your WordPress table!

## File Summary

- `lab.qmd` - Current basic version (static table, no images)
- `lab-full-featured.qmd` - ⭐ **Interactive table + images** (recommended)
- `lab-interactive-table.qmd` - Interactive table only
- `lab-javascript-table.qmd` - Interactive table (JavaScript, no R)
- `lab-with-images.qmd` - Images only, static table

## Need Help?

All versions are fully working - just pick one and rename it to `lab.qmd`!

**For most users: use `lab-full-featured.qmd`**
