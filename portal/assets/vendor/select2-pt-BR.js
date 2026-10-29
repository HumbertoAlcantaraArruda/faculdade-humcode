/*! Select2 4.1.0 | https://github.com/select2/select2/blob/master/LICENSE.md */

!function(){if(jQuery&&jQuery.fn&&jQuery.fn.select2&&jQuery.fn.select2.amd)var e=jQuery.fn.select2.amd;e.define("select2/i18n/pt-BR",[],function(){return{errorLoading:function(){return"Os resultados não puderam ser carregados."},inputTooLong:function(e){var n=e.input.length-e.maximum,r="Apague "+n+" caracter";return 1!=n&&(r+="es"),r},inputTooShort:function(e){return"Digite "+(e.minimum-e.input.length)+" ou mais caracteres"},loadingMore:function(){return"Carregando mais resultados…"},maximumSelected:function(e){var n="Você só pode selecionar "+e.maximum+" ite";return 1==e.maximum?n+="m":n+="ns",n},noResults:function(){return"Nenhum resultado encontrado"},searching:function(){return"Buscando…"},removeAllItems:function(){return"Remover todos os itens"},removeItem:function(){return"Remover item"},search:function(){return"Buscar"}}}),e.define,e.require}();
/*
The MIT License (MIT)

Copyright (c) 2012-2017 Kevin Brown, Igor Vaynberg, and Select2 contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

*/
