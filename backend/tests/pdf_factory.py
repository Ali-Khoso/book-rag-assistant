"""Create small, deterministic PDFs with known facts on known physical pages."""

from io import BytesIO
from textwrap import wrap

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject


FACT_PAGES = [
    "Astronomy: Jupiter is the largest planet in our solar system. Its Great Red Spot is a giant storm. The gas giant has many moons, including Europa and Ganymede. ",
    "Geology: Volcanoes erupt when pressure forces magma upward from beneath Earth's crust. Lava flows and volcanic ash are produced during eruptions. Magma becomes lava when it reaches the surface. ",
    "Biology: Photosynthesis allows plants to turn sunlight, water and carbon dioxide into glucose. Chlorophyll in leaves captures light energy. Plants release oxygen as a byproduct. ",
    "Ecology: Migratory birds travel between breeding grounds and winter habitats. Birds use the stars and Earth's magnetic field to navigate. Seasonal migration helps them find food. ",
]


def make_pdf(pages: list[str], *, encrypted: bool = False, image_only: bool = False, metadata: dict | None = None) -> bytes:
    """Place each string on its own PDF page using the standard Helvetica font."""
    writer = PdfWriter()
    if metadata:
        writer.add_metadata(metadata)
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica'), NameObject('/Encoding'): NameObject('/WinAnsiEncoding')})
        resources = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        if image_only:
            image = DecodedStreamObject()
            image.set_data(b'\x00\x00\x00')
            image.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'), NameObject('/Width'): NumberObject(1), NameObject('/Height'): NumberObject(1), NameObject('/ColorSpace'): NameObject('/DeviceRGB'), NameObject('/BitsPerComponent'): NumberObject(8)})
            resources[NameObject('/XObject')] = DictionaryObject({NameObject('/Im1'): writer._add_object(image)})
        page[NameObject('/Resources')] = resources
        lines = []
        for line in wrap(text, 85):
            escaped = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            lines.append(f'({escaped}) Tj 0 -13 Td')
        stream = DecodedStreamObject()
        stream.set_data(('BT /F1 10 Tf 50 740 Td ' + ' '.join(lines) + ' ET').encode('latin-1'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    if encrypted:
        writer.encrypt('test-password')
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
