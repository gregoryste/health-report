// Gera versões "fotografadas" de uma página de laudo com os filtros do próprio macOS (Core Image), para testar o OCR.
// Uso: osascript -l JavaScript ferramentas/degradar.js entrada.png pasta_saida
// Saída: <nome>_limpa.png, _inclinada.png, _escura.png, _desfocada.png, _sombra.png
ObjC.import('Foundation'); ObjC.import('AppKit'); ObjC.import('CoreImage');
function run(argv) {
  const entrada = argv[0], pasta = argv[1];
  const nome = $(entrada).lastPathComponent.stringByDeletingPathExtension.js;
  const base = $.CIImage.imageWithContentsOfURL($.NSURL.fileURLWithPath(entrada));
  const ext = base.extent, w = ext.size.width, h = ext.size.height;
  const filtro = (nomeF, img, params) => {
    const f = $.CIFilter.filterWithName(nomeF);
    if (img) f.setValueForKey(img, 'inputImage');
    for (const k in params) f.setValueForKey(params[k], k);
    return f.outputImage;
  };
  const vetor = (x, y) => $.CIVector.vectorWithXY(x, y);
  const branco = filtro('CIConstantColorGenerator', null, {inputColor: $.CIColor.colorWithRedGreenBlue(1, 1, 1)});
  const salvar = (img, sufixo) => {
    const recorte = filtro('CICrop', filtro('CISourceOverCompositing', img, {inputBackgroundImage: branco}),
                           {inputRectangle: $.CIVector.vectorWithXYZW(0, 0, w, h)});
    const rep = $.NSBitmapImageRep.alloc.initWithCIImage(recorte);
    const png = rep.representationUsingTypeProperties($.NSBitmapImageFileTypePNG, $());
    png.writeToFileAtomically(pasta + '/' + nome + '_' + sufixo + '.png', true);
  };
  salvar(base, 'limpa');
  const t = $.NSAffineTransform.transform; t.translateXByYBy(w / 2, h / 2); t.rotateByDegrees(4); t.translateXByYBy(-w / 2, -h / 2);
  const girada = filtro('CIAffineTransform', base, {inputTransform: t});
  salvar(filtro('CIPerspectiveTransform', girada, {inputTopLeft: vetor(40, h - 20), inputTopRight: vetor(w - 10, h),
                                                   inputBottomLeft: vetor(0, 0), inputBottomRight: vetor(w - 50, 30)}), 'inclinada');
  salvar(filtro('CIColorControls', filtro('CIExposureAdjust', base, {inputEV: -1.6}), {inputContrast: 0.6}), 'escura');
  salvar(filtro('CIGaussianBlur', base, {inputRadius: 1.8}), 'desfocada');
  const grad = filtro('CILinearGradient', null, {inputPoint0: vetor(0, 0), inputPoint1: vetor(w, h),
    inputColor0: $.CIColor.colorWithRedGreenBlue(0.35, 0.35, 0.35), inputColor1: $.CIColor.colorWithRedGreenBlue(1, 1, 1)});
  salvar(filtro('CIMultiplyCompositing', base, {inputBackgroundImage: grad}), 'sombra');
  return 'ok ' + nome;
}
