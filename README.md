# Spotibai

spotibai/
  server/    -> FastAPI + ytmusicapi (Render)   GET /home, GET /search
  android/   -> Kotlin + Jetpack Compose app

## Android (app/src/main/java/com/spotibai/app)
  Config.kt              BASE_URL (Render URL)
  SpotibaiApp.kt         Application: repository + image cache
  MainActivity.kt        edge-to-edge, theme
  data/model/            Track, HomeRow
  data/remote/           Retrofit (MusicApi, ApiClient)
  data/cache/            JsonCache (disk, stale-while-revalidate)
  data/repository/       MusicRepository
  ui/AppRoot.kt          tabs (hindi nire-rebuild), nav bar, player sheet
  ui/home/               Home rows
  ui/search/             Search + genre grid
  ui/player/             PlayerSheet (mini <-> music page), PlayerViewModel (queue/shuffle/repeat)
  ui/navigation/         FloatingNavBar
  ui/components/         FadeUpItem, Bounce, Skeleton, TrackCard, TrackRow
  ui/theme/              Colors, Theme
