"""Migration from per-composition visual models to one image model."""


def image_model(settings):
    if settings.gemini_image_model:
        return settings.gemini_image_model
    shares = settings.mix_shares
    if shares.get("pixiv_art") and settings.pixiv_gemini_model:
        return settings.pixiv_gemini_model
    if shares.get("manga") and settings.manga_gemini_model:
        return settings.manga_gemini_model
    return settings.gemini_model
