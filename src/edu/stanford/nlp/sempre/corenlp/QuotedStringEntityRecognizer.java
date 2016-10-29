package edu.stanford.nlp.sempre.corenlp;

import edu.stanford.nlp.sempre.LanguageInfo;

public class QuotedStringEntityRecognizer implements NamedEntityRecognizer {

  @Override
  public void recognize(LanguageInfo info) {
    int n = info.numTokens();
    for (int i = 0; i < n; i++) {
      if (!"``".equals(info.tokens.get(i)))
        continue;

      StringBuilder value = new StringBuilder();
      boolean closed = false;
      int j;
      for (j = i + 1; j < n; j++) {
        if ("''".equals(info.tokens.get(j))) {
          closed = true;
          break;
        }
        if (j > i + 1)
          value.append(' ');
        value.append(info.tokens.get(j));
      }
      if (closed) {
        for (int k = i; k < j + 1; k++) {
          info.nerTags.set(k, "QUOTED_STRING");
          info.nerValues.set(k, value.toString());
        }
      }
      i = j;
    }
  }

}
