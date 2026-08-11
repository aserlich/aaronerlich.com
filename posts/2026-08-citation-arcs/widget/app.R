## Citation-arcs widget — the browser-side (shinylive/webR) cut of
## github.com/aserlich/scholar-arcs. Self-contained on purpose: shinylive
## compiles one file, and the reader's browser runs it with no server involved.
##
## Deliberately uses jsonlite::fromJSON(url) rather than httr2. webR patches R's
## url() connections onto the browser's fetch, so that path works in WebAssembly;
## curl-based transports are far less reliable there. OpenAlex sends
## `access-control-allow-origin: *`, so the browser is allowed to read it.
##
## Trimmed relative to the full package: no Google Scholar (impossible in a
## browser — Scholar sends no CORS headers), no venue-tier editor, no peer
## sampling. Those live in the R package.

library(shiny)
library(bslib)
library(dplyr)
library(tidyr)
library(purrr)
library(tibble)
library(ggplot2)
library(jsonlite)

MAILTO <- "scholararcs@example.org"
HUES <- c("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300")

oa <- function(path, query = list()) {
  q <- paste(names(query), vapply(query, utils::URLencode, character(1), reserved = TRUE),
             sep = "=", collapse = "&")
  url <- sprintf("https://api.openalex.org/%s?%s&mailto=%s", path, q, MAILTO)
  tryCatch(jsonlite::fromJSON(url, simplifyVector = FALSE), error = function(e) NULL)
}
oid <- function(x) if (is.null(x)) NA_character_ else sub("^https://openalex.org/", "", x)

# Returns list(id, name) on success, "malformed" / "notfound" / "unreachable" on
# failure — the caller needs to tell them apart. Reporting a network blip as "no
# such ORCID" sends people off checking an identifier that was fine.
#
# Uses the filter form rather than authors/https://orcid.org/{id}: that variant
# embeds a full URL inside the path, and intermediaries that normalise "//" break
# it. The filter form has no such trap.
resolve_orcid <- function(orcid) {
  orcid <- sub("^https?://orcid\\.org/", "", trimws(orcid))
  if (!grepl("^[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X]$", orcid)) return("malformed")
  for (attempt in 1:2) {
    r <- oa("authors", list(filter = paste0("orcid:", orcid), per_page = "1"))
    if (!is.null(r$results)) {
      if (!length(r$results)) return("notfound")
      a <- r$results[[1]]
      return(list(id = oid(a$id), name = a$display_name %||% "?"))
    }
    Sys.sleep(1)
  }
  "unreachable"
}

search_authors <- function(name) {
  r <- oa("authors", list(search = name, per_page = "8"))
  if (is.null(r$results) || !length(r$results)) return(NULL)
  map_dfr(r$results, function(a) {
    inst <- a$last_known_institutions
    tibble(id = oid(a$id), name = a$display_name %||% "?",
           institution = if (length(inst)) (inst[[1]]$display_name %||% "—") else "—",
           works = as.integer(a$works_count %||% 0), cites = as.integer(a$cited_by_count %||% 0))
  })
}

fetch_works <- function(author_id) {
  r <- oa("works", list(
    filter = sprintf("author.id:%s,type:article", author_id),
    select = "id,display_name,publication_year,cited_by_count,counts_by_year,primary_location",
    `per-page` = "200"))
  if (is.null(r$results) || !length(r$results)) return(NULL)
  map_dfr(r$results, function(w) {
    cby <- w$counts_by_year %||% list()
    tibble(
      paper_id = oid(w$id),
      title    = w$display_name %||% "?",
      pub_year = as.integer(w$publication_year %||% NA),
      total    = as.integer(w$cited_by_count %||% 0),
      venue    = w$primary_location$source$display_name %||% NA_character_,
      counts   = list(if (length(cby))
        tibble(year = map_int(cby, ~ as.integer(.x$year)),
               cites = map_dbl(cby, ~ as.numeric(.x$cited_by_count)))
        else tibble(year = integer(), cites = numeric())))
  }) |> filter(!is.na(pub_year))
}

# One row per paper x year. Citations predating publication keep a negative
# offset; the current calendar year is carried but flagged partial.
build_series <- function(w) {
  this_year <- as.integer(format(Sys.Date(), "%Y"))
  long <- map_dfr(seq_len(nrow(w)), function(i) {
    cy <- w$counts[[i]]
    if (!nrow(cy)) cy <- tibble(year = w$pub_year[i], cites = 0)
    mutate(cy, paper_id = w$paper_id[i])
  }) |> filter(year <= this_year)

  w |> select(paper_id, title, pub_year, venue) |>
    left_join(summarise(group_by(long, paper_id), first = min(year), .groups = "drop"),
              by = "paper_id") |>
    mutate(start = pmin(pub_year, coalesce(first, pub_year)),
           year = map2(start, this_year, ~ seq.int(.x, .y))) |>
    unnest_longer(year) |>
    left_join(long, by = c("paper_id", "year")) |>
    mutate(cites = coalesce(cites, 0)) |>
    arrange(paper_id, year) |>
    group_by(paper_id) |>
    mutate(cum_cites = cumsum(cites)) |>
    ungroup() |>
    mutate(years_since_pub = year - pub_year,
           partial = year >= this_year,
           tier = "All papers")
}

# Tier venues against journals in the author's own topic area. Ranking against
# anything else -- a name search, or a sample of articles -- gives nonsense; see
# the package for the three attempts that failed.
tier_of <- function(w, author_id) {
  r <- oa("works", list(filter = sprintf("author.id:%s,type:article", author_id),
                        select = "primary_topic", `per-page` = "100"))
  tids <- if (!is.null(r$results))
    unique(na.omit(map_chr(r$results, ~ oid(.x$primary_topic$id)))) else character()
  if (!length(tids)) return(NULL)
  tids <- head(tids, 5)
  s <- oa("sources", list(
    filter = sprintf("topics.id:%s,type:journal,works_count:>50,summary_stats.2yr_mean_citedness:>0",
                     paste(tids, collapse = "|")),
    select = "display_name,summary_stats", `per-page` = "200", sort = "works_count:desc"))
  ref <- if (!is.null(s$results))
    na.omit(map_dbl(s$results, ~ as.numeric(.x$summary_stats$`2yr_mean_citedness` %||% NA))) else numeric()
  if (length(ref) < 20) return(NULL)
  brk <- quantile(ref, c(0.90, 0.75, 0.50), na.rm = TRUE)
  labs <- c("Top decile", "Top quartile", "Upper half", "Rest")

  vn <- unique(na.omit(w$venue))
  vs <- oa("sources", list(filter = paste0("display_name.search:", paste(vn[1], collapse = "")),
                           select = "display_name", `per-page` = "1"))  # warm-up, ignored
  cite_of <- setNames(rep(NA_real_, length(vn)), vn)
  # Look venues up in bulk by name; OpenAlex has no multi-name filter, so pull the
  # author's own sources from their works instead.
  sr <- oa("works", list(filter = sprintf("author.id:%s,type:article", author_id),
                         select = "primary_location", `per-page` = "200"))
  sids <- unique(na.omit(map_chr(sr$results %||% list(), ~ oid(.x$primary_location$source$id))))
  if (!length(sids)) return(NULL)
  st <- oa("sources", list(filter = paste0("ids.openalex:", paste(sids, collapse = "|")),
                           select = "display_name,summary_stats", `per-page` = "200"))
  if (is.null(st$results)) return(NULL)
  lut <- map_dfr(st$results, ~ tibble(
    venue = .x$display_name %||% NA_character_,
    citedness = as.numeric(.x$summary_stats$`2yr_mean_citedness` %||% NA)))
  lut |> mutate(tier = vapply(citedness, function(c) {
    if (is.na(c)) return("Rest")
    labs[which(c >= brk)[1] %||% length(labs)] }, character(1)),
    tier = ifelse(is.na(tier), "Rest", tier)) |>
    select(venue, tier)
}

pal <- function(g) setNames(rep(HUES, length.out = nlevels(g)), levels(g))

base_theme <- theme_minimal(base_size = 12) +
  theme(panel.grid.minor = element_blank(),
        panel.grid.major = element_line(colour = "#e1e0d9", linewidth = 0.3),
        strip.text = element_text(face = "bold", size = 9, hjust = 0),
        plot.title = element_text(face = "bold"),
        plot.subtitle = element_text(size = 8, colour = "#52514e"))

layers_of <- function(s, xv) list(
  solid  = filter(s, !partial),
  bridge = s |> group_by(paper_id) |> filter(any(partial)) |>
    filter(years_since_pub >= max(c(years_since_pub[!partial], -Inf))) |> ungroup(),
  ends   = s |> filter(!partial) |> group_by(paper_id) |>
    slice_max({{ xv }}, n = 1, with_ties = FALSE) |> ungroup())

ui <- page_sidebar(
  title = "Citation arcs",
  theme = bs_theme(version = 5, primary = "#2a78d6"),
  sidebar = sidebar(
    width = 300,
    textInput("orcid", "Your ORCID", placeholder = "0000-0001-6571-9081"),
    actionButton("go", "Draw my arcs", class = "btn-primary btn-sm"),
    hr(),
    textInput("nm", "…or search by name"),
    actionButton("srch", "Search", class = "btn-sm"),
    uiOutput("cands"),
    hr(),
    div(class = "small text-muted",
        "Runs entirely in your browser using OpenAlex — nothing is sent anywhere else. ",
        "OpenAlex reports fewer citations than Google Scholar but ranks papers similarly.")),
  uiOutput("msg"),
  navset_card_tab(
    nav_panel("Aligned on publication",
      plotOutput("p2", height = "520px",
                 hover = hoverOpts("h2", delay = 80, delayType = "debounce")),
      uiOutput("hov2"),
      helpText("Every paper restarted at its own year zero. x < 0 means it was cited as a preprint. ",
               "Hover a line to see which paper it is.")),
    nav_panel("The arc",
      plotOutput("p3", height = "520px",
                 hover = hoverOpts("h3", delay = 80, delayType = "debounce")),
      uiOutput("hov3"),
      helpText("Citations per year, not cumulative — the only view that shows when a paper peaked.")),
    nav_panel("Calendar time",
      plotOutput("p1", height = "520px",
                 hover = hoverOpts("h1", delay = 80, delayType = "debounce")),
      uiOutput("hov1"),
      helpText("Dominated by age: older papers have had longer to accumulate."))))

server <- function(input, output, session) {
  rv <- reactiveValues(s = NULL, msg = NULL, cands = NULL)
  say <- function(t, ok = TRUE) rv$msg <- list(t = t, ok = ok)

  output$msg <- renderUI({
    m <- rv$msg; if (is.null(m)) return(NULL)
    div(class = paste("alert py-2", if (m$ok) "alert-info" else "alert-danger"), m$t)
  })

  load_author <- function(id, label) {
    withProgress(message = "Fetching from OpenAlex", value = 0.3, {
      w <- fetch_works(id)
      if (is.null(w) || !nrow(w)) return(say("No journal articles found for that profile.", FALSE))
      setProgress(0.7, detail = "tiering venues")
      tv <- tryCatch(tier_of(w, id), error = function(e) NULL)
      s <- build_series(w)
      if (!is.null(tv) && nrow(tv)) {
        s <- s |> left_join(tv, by = "venue") |>
          mutate(tier = coalesce(tier.y, "Rest")) |> select(-tier.x, -tier.y)
      }
      lv <- intersect(c("Top decile", "Top quartile", "Upper half", "Rest", "All papers"),
                      unique(s$tier))
      rv$s <- mutate(s, tier = factor(tier, levels = lv))
      say(sprintf("%s — %d papers, %d citations.", label, n_distinct(w$paper_id), sum(w$total)))
    })
  }

  observeEvent(input$go, {
    req(nzchar(input$orcid))
    a <- resolve_orcid(input$orcid)
    if (identical(a, "malformed"))
      return(say("That does not look like an ORCID. They run 0000-0000-0000-0000.", FALSE))
    if (identical(a, "notfound"))
      return(say("That ORCID is valid but OpenAlex has no author record attached to it. Try searching your name instead.", FALSE))
    if (identical(a, "unreachable"))
      return(say("Could not reach OpenAlex just now — your ORCID is probably fine. Try again in a moment.", FALSE))
    load_author(a$id, a$name)
  })

  observeEvent(input$srch, {
    req(nzchar(input$nm))
    c <- search_authors(input$nm)
    if (is.null(c)) return(say("No authors matched.", FALSE))
    rv$cands <- c
    output$cands <- renderUI(tagList(
      helpText("Pick your profile — check the work count; OpenAlex sometimes merges two people."),
      radioButtons("cand", NULL, choiceValues = c$id, selected = character(0),
        choiceNames = lapply(seq_len(nrow(c)), function(i) HTML(sprintf(
          "<b>%s</b><br><span class='small text-muted'>%s · %d works</span>",
          c$name[i], c$institution[i], c$works[i])))),
      actionButton("pick", "Use this profile", class = "btn-primary btn-sm")))
  })

  observeEvent(input$pick, {
    req(input$cand)
    r <- filter(rv$cands, id == input$cand)
    load_author(r$id[1], r$name[1])
  })

  facet_if <- function(s) if (n_distinct(s$tier) > 1) facet_wrap(~tier, ncol = 2) else NULL

  # Hover readout. nearPoints() handles the facets as long as the panel variable
  # is a column of the data, which `tier` is. Matching on the plotted points means
  # a hover anywhere along a line finds the year you are actually over, so the
  # readout can report the value at that point rather than just the paper.
  hover_card <- function(hv, df, xv, yv, valfmt) {
    if (is.null(hv)) return(NULL)
    np <- nearPoints(df, hv, xvar = xv, yvar = yv, threshold = 30, maxpoints = 1)
    if (!nrow(np)) return(
      div(class = "text-muted small", style = "min-height:3.2em;padding:.4rem .2rem;",
          "Hover a line to identify the paper."))
    div(class = "small", style = "min-height:3.2em;padding:.4rem .2rem;border-left:3px solid #2a78d6;padding-left:.6rem;",
        tags$b(np$title[1]),
        tags$br(),
        sprintf("%s · published %d · %s",
                np$venue[1] %||% "venue unknown", np$pub_year[1], valfmt(np)))
  }

  hov_df <- reactive(req(rv$s))

  output$hov1 <- renderUI(hover_card(
    input$h1, filter(hov_df(), !partial), "year", "cum_cites",
    function(p) sprintf("%d citations by %d", p$cum_cites[1], p$year[1])))

  output$hov2 <- renderUI(hover_card(
    input$h2, filter(hov_df(), !partial), "years_since_pub", "cum_cites",
    function(p) sprintf("%d citations %d years after publication",
                        p$cum_cites[1], p$years_since_pub[1])))

  output$hov3 <- renderUI(hover_card(
    input$h3, filter(hov_df(), !partial), "years_since_pub", "cites",
    function(p) sprintf("%d citations in year %d", p$cites[1], p$years_since_pub[1])))

  output$p1 <- renderPlot({
    s <- req(rv$s); L <- layers_of(s, year)
    ggplot(mapping = aes(year, cum_cites, group = paper_id, colour = tier)) +
      geom_line(data = L$solid, linewidth = 0.7) +
      geom_line(data = L$bridge, linewidth = 0.7, linetype = "22") +
      geom_point(data = L$ends, size = 1.1) +
      scale_colour_manual(values = pal(s$tier), name = NULL) +
      labs(title = "Cumulative citations, calendar time", x = NULL, y = "Cumulative citations",
           subtitle = "Dashed tail = the current, incomplete year") +
      base_theme + theme(legend.position = "top")
  }, res = 100)

  output$p2 <- renderPlot({
    s <- req(rv$s); L <- layers_of(s, years_since_pub)
    ctx <- s |> filter(!partial) |> select(paper_id, years_since_pub, cum_cites)
    ggplot(mapping = aes(years_since_pub, cum_cites, group = paper_id, colour = tier)) +
      geom_line(data = ctx, aes(years_since_pub, cum_cites, group = paper_id),
                inherit.aes = FALSE, colour = "#e1e0d9", linewidth = 0.35) +
      geom_vline(xintercept = 0, colour = "#c3c2b7", linewidth = 0.4) +
      geom_line(data = L$solid, linewidth = 0.7) +
      geom_line(data = L$bridge, linewidth = 0.7, linetype = "22") +
      geom_point(data = L$ends, size = 1.1) +
      facet_if(s) +
      scale_colour_manual(values = pal(s$tier), guide = "none") +
      labs(title = "Cumulative citations by years since publication",
           subtitle = "Grey = all papers · x < 0 = cited before publication",
           x = "Years since publication", y = "Cumulative citations") +
      base_theme
  }, res = 100)

  output$p3 <- renderPlot({
    s <- req(rv$s) |> filter(!partial)
    ctx <- select(s, paper_id, years_since_pub, cites)
    med <- s |> filter(years_since_pub >= 0) |>
      group_by(tier, years_since_pub) |>
      summarise(m = median(cites), n = n_distinct(paper_id), .groups = "drop") |>
      arrange(tier, years_since_pub) |> group_by(tier) |> filter(cumall(n >= 3)) |> ungroup()
    ggplot(mapping = aes(years_since_pub, cites, group = paper_id, colour = tier)) +
      geom_line(data = ctx, aes(years_since_pub, cites, group = paper_id),
                inherit.aes = FALSE, colour = "#e1e0d9", linewidth = 0.35) +
      geom_vline(xintercept = 0, colour = "#c3c2b7", linewidth = 0.4) +
      geom_line(data = s, linewidth = 0.7) +
      geom_point(data = s |> group_by(paper_id) |> filter(n() == 1) |> ungroup(), size = 1.1) +
      { if (nrow(med)) geom_line(data = med, aes(years_since_pub, m), inherit.aes = FALSE,
                                 colour = "#0b0b0b", linewidth = 0.9, linetype = "22") } +
      facet_if(s) +
      scale_colour_manual(values = pal(s$tier), guide = "none") +
      labs(title = "The arc: citations per year",
           subtitle = "Annual rate · dashed black = tier median while n ≥ 3 · partial year excluded",
           x = "Years since publication", y = "Citations that year") +
      base_theme
  }, res = 100)
}

shinyApp(ui, server)
