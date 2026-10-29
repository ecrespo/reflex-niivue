import reflex as rx

config = rx.Config(
    app_name="niivue_demo",
    plugins=[rx.plugins.RadixThemesPlugin(theme=rx.theme(appearance="dark", accent_color="cyan"))],
    disable_plugins=[rx.plugins.SitemapPlugin],
)
