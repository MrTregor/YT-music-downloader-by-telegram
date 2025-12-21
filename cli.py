from downloader import download_audio, get_video_info, embed_metadata
from logger import logger


def main():
    logger.info('Запуск CLI')
    print("=== YouTube Audio Downloader ===")
    print("Введите URL видео для скачивания аудио")
    print("Команды: exit, quit - выход\n")

    while True:
        try:
            url = input("URL: ").strip()

            if not url:
                continue

            if url.lower() in ('exit', 'quit'):
                logger.info('Выход из CLI')
                print("Выход...")
                break

            if 'youtube.com' not in url and 'youtu.be' not in url:
                logger.warning(f'Некорректный URL: {url}')
                print("Ошибка: Введите корректную ссылку на YouTube видео\n")
                continue

            print("Получение информации о видео...")
            info = get_video_info(url)
            print(f"Название: {info['title']}")
            print(f"Автор: {info['uploader']}")
            print(f"Длительность: {info['duration']} сек")

            print("\nСкачивание аудио...")
            file_path = download_audio(url)

            print("Добавление метаданных...")
            embed_metadata(file_path, info['uploader'], info['title'], info['thumbnail'])

            print(f"\nГотово! Файл сохранен: {file_path}\n")

        except KeyboardInterrupt:
            logger.info('Прервано пользователем (Ctrl+C)')
            print("\n\nПрервано пользователем")
            break
        except Exception as e:
            logger.error(f'Ошибка: {e}', exc_info=True)
            print(f"Ошибка: {e}\n")


if __name__ == '__main__':
    main()
