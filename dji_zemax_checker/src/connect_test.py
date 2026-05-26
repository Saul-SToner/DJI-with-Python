import zospy as zp


def main() -> None:
    print("Initializing ZOSPy...")

    zos = zp.ZOS()

    print("Connecting to OpticStudio in extension mode...")
    oss = zos.connect("extension")

    print("Connected.")
    print("OpticStudio system object:", oss)

    try:
        print("Number of surfaces:", oss.LDE.NumberOfSurfaces)
    except Exception as exc:
        print("Connected, but failed to read LDE.")
        print("Error:", repr(exc))


if __name__ == "__main__":
    main()
